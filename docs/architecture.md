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

## 自動卡片定位

`image/card_detection.py` 處理傳統影像幾何；`pipeline/auto_scan.py` 串接資料、產生 Schema v1 Layout 與 CLI 輸出。原有 Loader、Resolver、Cropper、Overlay 介面不變；Catalog 不參與定位。

```text
原圖 → prepare_image → 灰階、方向性梯度遮罩、Canny（共用一次前處理）
                         ↓
detect_anchor → detect_card → validate_card → 保留有效列
                         ↓
                 detect_next_row → 重用候選偵測與驗證
                         ↓
有效列 → expand_grid → Schema v1 → Loader／Resolver → 再次邊界驗證
                                                        ↓
                                      crop_cards + draw_overlay + manifest
```

所有運算保留原圖解析度。Sobel 取各色彩通道的最大梯度，避免等亮度彩色邊框在灰階中消失；依梯度方向分出垂直與水平邊緣。HoughLinesP 找上方近水平、足夠長且有局部亮度對比的白線，合併重複／斷裂線段後取白線中心，避免透明白線在暗背景上被絕對白色閾值漏掉。

`detect_card()` 在 Anchor 右下方的有限搜尋帶，透過形態學連接與方向投影找出持續側邊，配對寬度合理的側邊，再找影像實際存在的上下邊。搜尋區包含 Anchor 本身，允許完整卡片貼近列表白線。候選保留 `visible_top`／`visible_bottom` 及可缺失的 `top`／`bottom`；可見高度不代表完整高度。候選評分包含邊緣支持、比例、側邊端點與水平邊距離，以及可選參考尺寸；先由高支持候選確立第一欄，再依側邊區段區分列，避免裁切列第二欄的立繪內部線條搶先成為基準。較早的同欄不完整側邊仍保留給下一列定位。

`validate_card()` 才決定能否裁切：寬高比限制為 0.43～0.58，左右邊覆蓋至少 65%、頂邊至少 55%、底邊至少 60%，並確認角點鄰域、底部側邊延伸及間隙。支持度在隨卡寬縮放的窄帶內計算，容忍邊框厚度與斜切角。跨越畫面的連續橫線、延續至兩側間隙的疑似 UI 底邊、兩側同時向下延伸都可能造成拒絕；單側背景直線不再獨自否決完整卡片。跨間隙橫線必須位於底邊相同的窄 Y 範圍，避免把幾像素外的背景橫線算入。這些是保守影像規則，不是機體辨識或遮擋分類器；規則閾值仍需更多裝置素材驗證。

不完整第一列只提供可信的 X 範圍、寬度與可見端點，供 `detect_next_row()` 向下建立一次有限搜尋帶；無候選時使用有界的下一搜尋帶重新偵測，不補造完整高度。第一列有效時最多檢查第二列；只有初始列無效且第二列有效，才繼續第三列。第二列無效立即停止，最多保留兩列。無法取得可靠幾何時可能回報無有效卡片。

`expand_grid()` 對有效列垂直邊緣投影做一維自相關，在卡寬 1.05～1.55 倍的範圍估計水平週期，再以多組接近預測的實測邊界斜率中位數修正；修正只有在整列左右邊對齊分數不降低時才採用，避免立繪內部峰值造成累積漂移。第二有效列可參考已驗證週期。在原始底邊上下 6% 卡寬的窄範圍，收集各卡片實際水平邊界，選擇能讓同列最多卡片通過驗證的共同底邊，再以支持度與偏移量評分；不以頂部加預估高度補造底邊。最多預測 8 欄，每個位置重用 `validate_card()`，不保證固定輸出 8 張；沒有週期證據時只保留基準卡片。

自動流程保留實際列表列欄編號，跳過第一列後輸出的列號為 1、2。匯出先嘗試完整雙列網格，不能表示時按各列連續有效區段拆成多份既有 Schema v1，不改 Schema、不補缺洞。標準化整數取整後重新經 Loader／Resolver，並驗證實際像素矩形；裁切與 manifest 使用這份已驗證的匯出幾何。manifest 的 `detected_bounds` 保留取整前偵測框，`bounds` 為實際裁切框；`layout_file`／`layout_index` 對應匯出 Layout 的局部編號。這些資料不屬於 Inventory。

CLI 不覆寫既有目錄。無卡片時保留 `overlay.png` 與失敗階段／原因，退出碼 1；成功時另外輸出 Layout 與卡片。磁碟中途失敗可能留下部分檔案，需使用新目錄重試。

測試包括已知像素框的合成圖、貼近 Anchor、初始列截斷後兩列有效、操作列遮擋、單側背景延伸、鄰近橫線、底邊光暈、缺欄、5 欄、縮放、JPEG、Unicode 路徑與 Layout 重載後逐像素裁切比對。本機九張 2388×1668 真實圖涵蓋 SR／SSR／UR 各三種捲動情況，每張取 16 張，與目視檢查的結構外框座標比較最低 IoU 為 0.912；不把發光範圍當作結構外框。原始 UR 圖（`Test_UR.png`，原 `Test.png`）另測試縮放 0.65／1.3 倍與 JPEG 品質 70，保留框 IoU 大於 0.90，JPEG 允許保守漏掉 1 張。標註只供測試，不傳給偵測器；這不是其他裝置的驗證結果。

OpenCV API 透過 Context7 查閱官方 4.13.0 文件（Sobel、形態學與 HoughLinesP）；Context7 未提供 4.14.0 文件版本，實際執行環境為 OpenCV 4.14.0、NumPy 2.5.4、Python 3.13.16。

## 工作目錄中的幾何 ROI 實驗

以下為相對 `f8cfbe5` 的未提交實驗，沿用既有 Schema 與上述主流程。初始搜尋區為白線兩端之間、白線往下到圖片底部，不再用圖片寬 18%／高 60% 或卡片寬占整張圖的比例限制候選。寬度的下限來自梯度濾波的可分辨範圍，上限來自搜尋區及卡片寬高比的幾何可容納範圍。

`prepare_image()` 量測垂直梯度遮罩橫向連續區段的中位厚度，加入 Gaussian／Sobel 各一像素的足跡作為邊緣半徑。候選側邊配對與斷邊連接改用此半徑；避免放大搜尋區後，寬候選使用過大連接核，把多列拼成一張大卡片。

`edge_tolerance()` 在排除斜切角的側邊取樣，以邊緣半寬、中心偏移及偏移 MAD 的三倍，加上兩像素濾波足跡估計位置誤差。下一列 X 範圍是前一張左右邊各加此誤差，Y 從前一張可見結束處加誤差開始，到圖片底部停止；不預設列間距，也不以可見高度代表完整高度。若沒有任何候選側邊，初始搜尋已涵蓋圖片剩餘範圍，便停止，不再用畫面高度百分比猜下一列位置。

有完整參考卡片時，`detect_card()` 只在參考卡高加減兩倍位置誤差的區間找實際底邊；只有部分側邊時，使用同一寬高比先驗。Pipeline 將已驗證網格的第一張卡片幾何傳給下一列，避免把尚未校正的光暈位置當成高度。最多列數與遇到不完整第二列就停止的規則不變。新增測試涵蓋畫布加寬、增大列間距、缺少幾何時終止，以及不得略過不完整第二列去取第三列。

實驗輸出按 `outputs/<裝置名稱>/geometry_roi/<測資名稱>/` 保存。`scripts/layout_batch.py` 以獨立程序比較已提交基準與工作目錄，36 次測試結果保留在 `outputs/summary.json`；案例的 `run.json` 記錄來源雜湊、退出碼及像素／Layout 核對數，`versions.json` 記錄兩版來源。iPhone 裁切列仍有誤判與原版匯出失敗，輸出數不等於正確卡片數。初始搜尋面積增加會帶來執行成本；Anchor 的上方區域比例、垂直邊緣提取的尺度及既有支持度門檻仍未自適應化，不能把本次結果視為已消除所有經驗常數。

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

本機 `tests/fixtures/private/IPad/Test_UR.png`（相容舊平面目錄）僅作額外驗證；檔案不存在時略過該項，不妨礙公開測試。真實截圖、衍生裁切與 Overlay 均不納入 Git。手動 Profile [`test_screenshot.json`](../data/profiles/test_screenshot.json) 僅描述這張 2388×1668 圖片前兩排的 16 個完整卡片區域，未辨識任何遊戲資料。

驗證環境：Python 3.13.16、OpenCV 4.14.0、NumPy 2.5.4、pytest 9.2.0。Context7 未提供完全對應的 OpenCV 4.14／NumPy 2.5 文件版本，已查閱鄰近版本官方文件，並以實際安裝版本的執行測試驗證用到的 API；Python 其他版本尚未實測。

參考文件：[OpenCV 透視轉換](https://github.com/opencv/opencv/blob/4.13.0/doc/py_tutorials/py_imgproc/py_geometric_transformations/py_geometric_transformations.markdown)、[NumPy 複本與視圖](https://numpy.org/doc/2.4/user/basics.copies.html)、[pytest 暫存目錄](https://docs.pytest.org/en/stable/how-to/tmp_path.html)。
