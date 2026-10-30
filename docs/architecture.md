# 架構與幾何規則

本文件說明「單張圖片 + 明確 Layout → 卡片圖片與 Debug Overlay」的幾何模組。這些模組不解析機體名稱、稀有度、持有狀態，也不產生 Inventory；獨立的機體識別 Catalog 與離線匯入見 [catalog.md](catalog.md)。

## 模組與資料流

```text
JSON 檔案 → config/layout_loader.py → LayoutProfile
                                          ↓
圖片尺寸與可選 Viewport → image/layout.py → ResolvedLayout
                                              ├─ image/cropper.py → CropResult[]
圖片陣列 ─────────────────────────────────────└─ image/debug_overlay.py → 標記圖片複本

pipeline/quick_scan.py：協調以上步驟；其中 CLI 額外負責圖片讀寫與輸出 manifest
```

- `config/layout_models.py`：不可變的 `GridSpec`、`LayoutProfile`、`ResolvedCard`、`ResolvedLayout`，以及共用四邊形驗證。Profile 中的座標與步進會轉成巢狀 tuple，避免外部修改原始 JSON 物件影響設定。
- `config/layout_loader.py`：嚴格讀取 Schema v1，拒絕缺少欄位、未知欄位、重複 JSON key、不支援的版本或座標系統。整數欄位不接受布林值或浮點數。
- `image/layout.py`：依圖片尺寸、Viewport 與設定展開卡片。沒有手機型號、畫面偵測或跨畫面狀態。
- `image/cropper.py`：驗證來源圖片與解析結果，回傳獨立的卡片圖片陣列；不寫檔、不推測畫面、不修改設定。
- `image/debug_overlay.py`：在 BGR 複本上繪圖；灰階與 BGRA 來源會轉換為 BGR，原圖不變。
- `pipeline/quick_scan.py`：`quick_scan()` 是記憶體內 API。`main()` 是 CLI，委派既有模組處理幾何。

## Layout Schema v1

完整範例為 [`sample_grid.json`](../data/profiles/sample_grid.json)。必要欄位如下：

| 欄位 | 意義與限制 |
| --- | --- |
| `schema_version` | 整數 `1` |
| `profile_id` | 非空字串，識別這份幾何設定 |
| `coordinate_system.type` | 固定 `normalized_integer` |
| `coordinate_system.scale` | 整數 `10000` |
| `coordinate_system.point_order` | 固定 `["TL", "TR", "BR", "BL"]` |
| `screen.reference_size` | `[width, height]`，正整數，對應有效畫面的比例 |
| `grid.rows`、`grid.columns` | 正整數；排數完全由設定決定 |
| `grid.first_card` | 第一張卡片的四個標準化整數頂點，每軸介於 0～10000 |
| `grid.horizontal_step` | 每增加一欄的 `[dx, dy]`，兩軸皆可非零或為負 |
| `grid.vertical_step` | 每增加一排的 `[dx, dy]`，兩軸皆可非零或為負 |

存在多欄或多排時，對應位移向量不能為零。允許卡片區域重疊，不會推測是否為設定錯誤，也不做去重。

## Viewport 與比例相容性

預設整張原圖為有效區域。API／CLI 可提供像素邊界 `(left, top, right, bottom)`，右、下邊界不包含在切片中，且必須完整位於原圖內。Viewport 是本次解析的顯式輸入，不是藏在 Cropper 裡的設定，也不是 Schema v1 的額外欄位。

`reference_size` 對應有效區域，而非一律對應整張原圖。令有效寬高為 `W, H`，參考寬高為 `Rw, Rh`，必須滿足：

```text
W × Rh == H × Rw
```

使用整數交叉乘法，不使用浮點容許誤差。例如 1920×1080 與 1280×720 相容；1920×1081 不相容。程式不自動修正黑邊、UI 縮放、旋轉或不同排版。同一份 Layout 只能同比例縮放；比例相同也不代表卡片位置一定相同，仍須以 Overlay 檢查。

## 網格展開與像素邊界

原點在有效畫面左上，X 向右、Y 向下。標準化座標 `10000` 代表該軸完整長度。

```text
P(row, column, vertex) = P0(vertex) + column × Hstep + row × Vstep
pixel_x = viewport.left + normalized_x × viewport.width / 10000
pixel_y = viewport.top  + normalized_y × viewport.height / 10000
index = row × columns + column
```

例如 1920×1080 原圖中的 `(1000, 1000)` 對應 `(192, 108)` 像素邊界。8 欄 × 2 排展開為 16 張卡片、64 個頂點。時間與儲存空間皆為 O(rows × columns)。先檢查所有展開頂點是否仍在標準化範圍內，再轉成像素，不默默截斷越界卡片。

`ResolvedCard.vertices` 保留浮點座標，描述連續的像素**邊界**。像素 `(x, y)` 佔據 `[x, x+1) × [y, y+1)`；圖片邊界可以等於 `width` 或 `height`，但不是可直接索引的像素。

外接矩形採左、上界 `floor(min)`，右、下界 `ceil(max)`，以 `image[top:bottom, left:right]` 裁切。例：範圍 `[16.65, 43.29)` 包含 16～43 號像素，輸出寬度 28。Overlay 顯示時才以 `floor(value + 0.5)` 取最近像素中心，最外邊界畫在最後一列／欄；顯示上的限制不會改變裁切幾何。

## 頂點與四邊形驗證

要求順序為 TL → TR → BR → BL，且為嚴格凸四邊形。檢查四點、有效座標、範圍、重複頂點、零面積、共線、自交及凹形。

實作檢查圖片座標系中的連續邊叉積皆大於零，同時要求：

```text
TL.x < TR.x     BL.x < BR.x
TL.y < BL.y     TR.y < BR.y
```

因此不會只靠順／逆時針判斷標籤：循環移位但繞行方向相同的頂點，也會被拒絕。這項語意限制適合目前直立卡片，並不接受任意旋轉 90 度的卡片標記；需要時應明確修訂規格。

## 裁切與錯誤處理

輸入圖片支援非空的 `uint8` 灰階、BGR、BGRA NumPy 陣列；不自動壓縮 16-bit 或浮點圖片。圖片尺寸必須與 `ResolvedLayout.image_size` 完全一致，避免誤用其他圖片的解析結果。

- `bbox`：預設，依外接矩形複製圖片；傾斜卡片的角落可能包含背景。
- `perspective`：將四點映射到矩形。未指定尺寸時，寬度取上下邊較長者向上取整，高度取左右邊較長者向上取整，各至少 1 像素；可顯式指定 `(width, height)`。這是可見幾何估算，不能還原未知的真實卡片比例。

透視轉換使用 `getPerspectiveTransform`、`warpPerspective`、雙線性插值與邊界複製。為銜接像素邊界定義，來源點減去 0.5，目的邊界為 `(-0.5, -0.5)` 至 `(width-0.5, height-0.5)`；整數矩形在相同輸出尺寸下會與普通切片逐像素相同。邊緣插值可能混合附近背景，這不是辨識或去背工具。

JSON、Schema、比例與網格越界以 `LayoutError` 回報，未完成解析不會回傳部分 Layout。Cropper 對來源圖片不相容直接報錯；個別卡片幾何或 OpenCV 裁切失敗則回傳 `CropResult(status="error", image=None, error=...)`，保留其他卡片結果。

CLI 在裁切與 Overlay 成功後才建立輸出目錄，不覆寫既有目錄。失敗以非零退出碼及訊息回報。若磁碟寫入中途失敗，可能留下部分輸出，需改用新的目錄重試；不會宣稱本次成功。

`manifest.json` 只記錄本次裁切的幾何、尺寸、狀態與檔名，沒有帳號資訊或遊戲辨識結果。

## Python 使用方式

```python
import cv2
from gget_scanner.config.layout_loader import load_layout
from gget_scanner.image.cropper import CropOptions
from gget_scanner.pipeline.quick_scan import quick_scan

image = cv2.imread("screenshot.png")
profile = load_layout("data/profiles/sample_grid.json")
result = quick_scan(image, profile, crop_options=CropOptions("bbox"))

for crop in result.crops:
    if crop.status == "ok":
        print(crop.card.index, crop.image.shape)
    else:
        print(crop.card.index, crop.error)
```

獨立使用時可直接呼叫 `resolve_layout()`、`crop_cards()` 或 `draw_overlay()`。CLI 另使用 NumPy buffer 與 `Path` 處理圖片讀寫，以支援 Windows 中文路徑。

## 測試與資料保留

pytest 以合成圖片驗證 Schema、四邊形、比例、Viewport、取整、8×2 展開、斜向位移、裁切尺寸與逐像素內容、透視方向、不可變性、Overlay 位置、Unicode CLI 與覆寫保護。

本機 `tests/fixtures/private/Test.png` 僅作額外驗證；檔案不存在時略過該項，不妨礙公開測試。真實截圖、衍生裁切與 Overlay 均不納入 Git。手動 Profile [`test_screenshot.json`](../data/profiles/test_screenshot.json) 僅描述這張 2388×1668 圖片前兩排的 16 個完整卡片區域，未辨識任何遊戲資料。

驗證環境：Python 3.13.16、OpenCV 4.14.0、NumPy 2.5.4、pytest 9.2.0。Context7 未提供完全對應的 OpenCV 4.14／NumPy 2.5 文件版本，已查閱鄰近版本官方文件，並以實際安裝版本的執行測試驗證用到的 API；Python 其他版本尚未實測。

參考文件：[OpenCV 透視轉換](https://github.com/opencv/opencv/blob/4.13.0/doc/py_tutorials/py_imgproc/py_geometric_transformations/py_geometric_transformations.markdown)、[NumPy 複本與視圖](https://numpy.org/doc/2.4/user/basics.copies.html)、[pytest 暫存目錄](https://docs.pytest.org/en/stable/how-to/tmp_path.html)。
