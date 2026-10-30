# 卡片屬性辨識 MVP

輸入是已裁切的單張機體卡片；沿用 Python、OpenCV、NumPy，不訓練模型、不呼叫外部服務。既有 Layout／Cropper／Catalog 未修改。此模組只辨識卡片 UI 的稀有度與職能，不辨識機體身分、OCR、等級、星數或 SP／SSP。

使用者確認：左側粗框線金色為 SSR、藍色為 SR、彩色為 UR；紅色劍為 ATTACK、藍色盾為 DEFENSE、黃色彈藥為 SUPPORT。SP 標記不改變框線所表示的稀有度。**正式稀有度分類使用已標記樣本的 Lab 特徵比對，不在程式內寫死金色／藍色閾值，也不依輸入路徑或名稱猜答案。**

## 檔案與資料流

| 檔案 | 責任 |
| --- | --- |
| `src/gget_scanner/recognition/models.py` | 圖片、標準化、候選與結構化結果 |
| `recognition/config.py` | JSON 設定驗證與 ROI 縮放 |
| `recognition/normalizer.py` | 圖片驗證、比例檢查與尺寸標準化 |
| `recognition/rarity.py` | 三段粗框線 Lab 直方圖與近鄰距離 |
| `recognition/role.py` | HSV 區塊、梯度形狀與遮罩模板匹配 |
| `recognition/references.py` | 參考樣本載入、驗證及實際徽章提取工具 |
| `recognition/debug.py` | 獨立的可選 Debug 輸出 |
| `recognition/__init__.py` | 設定、標準化與錯誤型別匯出 |
| `src/gget_scanner/pipeline/card_attributes.py` | `classify_card`、可重用 `CardClassifier`、CLI 與評估 |
| `data/profiles/card_attributes.json` | 集中設定；與 Layout JSON 分開 |
| `tests/test_card_normalizer.py` | 標準化、原圖保留、比例與設定邊界 |
| `tests/test_card_classifiers.py` | 特徵、位移／縮放、背景干擾、拒答與嚴格篩選 |
| `tests/test_card_references.py` | 參考檔、模板提取、遮罩與標籤衝突 |
| `tests/test_card_attributes.py` | 單張／批次、Debug、錯誤隔離與評估 |

其他變更為 `pyproject.toml` 新增 `gget-classify` 入口，以及 README／roadmap 狀態更新。沒有新依賴。

```text
CropResult.image → Normalizer → normalized BGR ┬→ RarityClassifier
                     └→ original preserved   └→ RoleClassifier
                                                    ↓
                                     結果物件／JSON；另選 Debug
```

## 標準化與設定

預設尺寸 200×400，允許相對長寬比誤差 5%：`abs((width/height)/(target_width/target_height)-1)`。超出範圍回傳 `ASPECT_RATIO_MISMATCH`，不拉伸、不分類。縮小採 INTER_AREA，放大或混合縮放採 INTER_LINEAR；沒有 padding。

輸入支援 uint8 灰階、BGR、全不透明 BGRA；灰階可標準化，但兩個色彩分類器均回傳 UNKNOWN。含透明像素的卡片回傳 `UNSUPPORTED_TRANSPARENCY`，不把透明 RGB 當成有效 UI 顏色。原圖陣列保留在 `result.normalization.original`，標準化圖在 `normalized`；處理流程不改寫原圖，呼叫端仍擁有其陣列。序列化不包含圖片陣列。

所有 ROI 為 `[left, top, right, bottom]` 半開區間，以 200×400 畫布為座標基準。修改目標尺寸後自動按比例換算；若 ROI 變空則拒絕設定。

- 粗框線三段：`[4,60,14,120]`、`[4,125,14,185]`、`[4,190,14,250]`。使用窄取樣帶，避免大面積卡片背景；仍可能被立繪遮擋。
- 職能搜尋區：`[15,0,85,60]`，不是固定徽章尺寸。鎖頭、星章不屬於模板。
- 設定包括比例誤差、直方圖 bins、近鄰數、各項門檻、HSV、候選區塊面積與模板尺度。JSON 拒絕未知／缺失欄位、重複 key、不合理值與不支援版本。

## 分類與分數

稀有度先轉 Lab，每段建立 8×8×8 聯合直方圖並正規化為總和 1。與各參考圖計算每段 Hellinger 距離，再平均三段。每類取最近至多 3 個樣本的平均距離；距離 **0 最相似、1 最不同**。接受條件包含足夠參考樣本、絕對距離、第一／二名差距、單段距離上限與三段判斷一致性。每類預設至少 2 個有效參考，缺類時允許候選但不接受結果。

職能先取得 HSV 紅／藍／黃候選連通區，不以搜尋區整體主色決定。接著在小搜尋區比對真實徽章的灰階梯度，採 `TM_CCORR_NORMED`，尺度 0.9／1.0／1.1，允許平移。alpha 作為二值遮罩，內縮一像素避開裁切邊緣梯度；零能量模板與非有限分數被拒絕。模板永遠以 200×400 的卡片座標提取，推論時再按目標尺寸縮放。

若全域顏色區塊與同色背景相連，模板仍可在原搜尋區定位；最後在匹配出的徽章遮罩內重新驗證顏色比例與局部連通區。顏色、形狀、候選差距需分別通過門檻，不混成「正確機率」。形狀分數越高越相似；JSON 亦保留各類局部顏色比例、模板路徑、位置與尺度。

`value` 只有 ACCEPTED 才提供類別，否則為 UNKNOWN；`best_candidate` 與 alternatives 仍保留候選。`reasons` 說明缺資料、框線遮擋、距離過大、候選接近或顏色／形狀衝突。某一分類器失敗不抹掉另一個結果。

`strict_filter_allowed` 預設 false。只有明確開啟 `strict_filter_enabled`、結果 ACCEPTED 且參考包沒有問題，才會為 true。**目前只驗證三種稀有度及有限 UI 樣本，請維持預設關閉；後續立繪匹配不應據此硬性排除其他類別。** N／R 可在取得真實標記資料後加入 `rarity.classes` 與參考 manifest，不需改分類核心；目前無法保證未知 N／R 不會與三類參考相近。

## 單張與批次使用

依 README 安裝 `.[dev]` 後執行。新 clone 不帶遊戲樣本，省略 `--references` 仍可測標準化與 UNKNOWN 行為。

```powershell
# 單張；使用此 worktree 已整理的本機參考包
.venv/Scripts/gget-classify.exe outputs/cards/initial/Test_UR/card_000_r0_c0.png --config data/profiles/card_attributes.json --references data/local_assets/recognition/mvp/references.json --output outputs/recognition/card_single_01 --debug

# 單一資料夾，不把 overlay／總覽當卡片
.venv/Scripts/gget-classify.exe outputs/cards/initial/Test_SSR --config data/profiles/card_attributes.json --references data/local_assets/recognition/mvp/references.json --output outputs/recognition/card_batch_01

# 已重新分類的整份測資；遞迴掃描，評估標記為 test 的部分
.venv/Scripts/gget-classify.exe data/local_assets/recognition/mvp/cards --recursive --config data/profiles/card_attributes.json --references data/local_assets/recognition/mvp/references.json --labels data/local_assets/recognition/mvp/labels.json --split test --output outputs/recognition/card_evaluation_01
```

也可使用 `.venv/Scripts/python.exe -m gget_scanner.pipeline.card_attributes`，參數相同。批次預設只讀 `card_*` 的 PNG／JPEG／WebP／BMP，單張輸入不限制檔名。輸出目錄必須全新；資料夾模式的輸出須在輸入目錄之外。單張損毀或比例異常不停止其他卡片；參考設定錯誤則先報錯。

結果位於 `results.json`，包含逐張完整分數、異常、平均耗時及參考包問題。有 labels 才計算準確率；無標籤的 `metrics` 為 null。退出碼 0 表示檔案處理完成（可以有 UNKNOWN）；1 表示有圖片錯誤、比例異常或參考包問題；2 表示命令／設定／輸出失敗。磁碟寫入失敗可能留下部分輸出，改用新目錄重試。

`--debug` 額外輸出 `normalized.png`、`regions.png`、三張 `border_*.png`、`role_search.png`、可取得時的 `badge_candidate.png`，以及含直方圖的 `scores.json`。紅框是最佳模板候選位置，即使結果拒答也會保留，不等於已確認的徽章。預設不寫這些圖片。

```python
from gget_scanner.recognition import load_config
from gget_scanner.recognition.references import load_references
from gget_scanner.pipeline.card_attributes import CardClassifier, classify_card

config = load_config("data/profiles/card_attributes.json")
references = load_references("data/local_assets/recognition/mvp/references.json", config)
classifier = CardClassifier(config, references)  # 批次時只建立一次

# 接在既有 quick_scan(...).crops 之後；不需改 Cropper
for crop in scan_result.crops:
    if crop.status == "ok":
        result = classifier.classify(crop.image)
        print(result.to_dict())

# 單張便利入口；重複處理時優先重用上面的 classifier
result = classify_card(card_image, config, references)
```

## 新增參考樣本與模板

參考包 JSON 的路徑相對於 JSON 所在目錄，不允許逃出該目錄。圖片放在本機忽略的 `data/local_assets/recognition/`。最小結構如下；這只是格式範例，每類至少需要 2 張有效卡片，三種職能都需有效模板，否則對應分類器會 UNKNOWN：

```json
{
  "schema_version": 1,
  "rarity_samples": [
    {"image": "cards/SSR/card_001.png", "label": "SSR", "group": "unique-card-artwork-001"}
  ],
  "role_templates": [
    {"image": "templates/ATTACK.png", "label": "ATTACK", "group": "badge-source-artwork-001"}
  ]
}
```

加入已人工標記的卡片並更新 manifest，重新載入即會自動標準化與提取特徵，不需另訓練或修改程式。不要重複同一張圖片來湊樣本數。缺失／無法解碼的個別參考會列出問題並停用嚴格篩選；相同檔案被標成矛盾類別時拒絕整包。輸出報告會揭露參考與模板錯誤。

提取真實職能模板，`--box` 是標準化後的座標，需先用 Debug 圖確認，只包含職能徽章：

```powershell
.venv/Scripts/python.exe -m gget_scanner.recognition.references outputs/cards/initial/Test_SSR/card_001_r0_c1.png --config data/profiles/card_attributes.json --label ATTACK --box 25 2 72 50 --output data/local_assets/recognition/mvp/templates/ATTACK_new.png
```

工具以指定顏色區塊產生 alpha，填補白色圖案內的孔洞。但同色背景可能污染自動遮罩，**新增模板必須檢視 alpha**。此情況可提供人工描繪的 uint8 灰階遮罩（尺寸與裁切 patch 相同；白色保留徽章、黑色排除背景）：

```powershell
.venv/Scripts/python.exe -m gget_scanner.recognition.references outputs/cards/initial/Test_SSR/card_000_r0_c0.png --config data/profiles/card_attributes.json --label SUPPORT --box 25 2 72 50 --mask data/local_assets/recognition/mvp/templates/SUPPORT_mask.png --output data/local_assets/recognition/mvp/templates/SUPPORT_new.png
```

將新 PNG 加入 `role_templates`；模板與 alpha 都不覆寫既有檔案。同職能可以有多個模板，不使用網路通用圖示。

## 重新分類的本機測資與實測

2026-10-30 已將 `outputs/cards/initial/Test*` 九個資料夾的 144 張卡片按實際框線與徽章重新標記，**複製**到 `data/local_assets/recognition/mvp/cards/<rarity>/<role>/`。原始 `outputs/cards/initial/Test*` 保留；`provenance.json` 紀錄來源、標籤及 SHA-256，副本內容與原圖一致。未以資料夾名作單張標籤：原 `Test_SR`／`Test_SR_touch_top` 前 5 張的金框卡已歸 SSR。

- SR 38、SSR 58、UR 48。
- ATTACK 73、DEFENSE 38、SUPPORT 33。
- `references.json` 選用每種稀有度各 3 張參考卡與每種職能各 1 張真實模板；支援徽章使用人工檢視的 alpha。
- `labels.json` 含 `image`、`rarity`、`role`、`group`、`split`；split 限 reference／calibration／test，兩種標籤可個別設 null。
- 重複卡面使用相同 group。15 張屬參考群組（其中實際取 9 張作稀有度參考）、33 張校準、96 張測試。評估會排除與參考包同 group 或相同檔案 SHA-256 的樣本，並列出排除數。

固定現有設定後，96 張測試結果如下，UNKNOWN 算入整體準確率分母：

| 項目 | 稀有度 | 職能 |
| --- | --- | --- |
| 正確／測試數 | 93／96（96.875%） | 96／96（100%） |
| UNKNOWN | 3／96（3.125%） | 0／96 |
| 已接受結果的錯誤數 | 0 | 0 |

稀有度混淆矩陣（列為真值、欄為輸出）：

| 真值 | SR | SSR | UR | UNKNOWN |
| --- | --- | --- | --- | --- |
| SR | 25 | 0 | 0 | 3 |
| SSR | 0 | 41 | 0 | 0 |
| UR | 0 | 0 | 27 | 0 |

職能為 ATTACK 52／52、DEFENSE 27／27、SUPPORT 17／17，無交叉誤分類。33 張校準集為稀有度 31／33（2 UNKNOWN）、職能 33／33；沒有為了消除 UNKNOWN 而放寬距離門檻。測試集三個稀有度拒答分別是兩張超級鋼彈與一張鋼彈 F90 的裁切，框線特徵距離過大，保留候選與原始分數。

單次測試集平均約 **7.18 ms／張**，包含圖片讀取、雜湊、標準化與分類，不包含參考包初次載入、Debug／JSON 寫入。這是本機單次量測，不是跨硬體效能保證。詳細本機結果與拒答 Debug 位於 `outputs/recognition/mvp/recognition-mvp-test/`；校準結果為 `outputs/recognition/calibration/recognition-calibration-reviewed-mask/`。圖片、標籤、參考 manifest 與測試報告均留本機，不提交 Git。

2026-10-31 已整理本機輸出，入口為 `outputs/README.md`。裝置測資在 `outputs/cards/IPad/`、`outputs/cards/iPhone13pro/`，最初九組裁切在 `outputs/cards/initial/`；分類報告在 `outputs/recognition/`，歷史腳本在 `outputs/archive/`。來源 provenance 與目前報告的路徑已同步更新，圖片與分類分數不變。舊路徑可查 `outputs/relocations-20261031.json`；archive 的一次性腳本保留原內容，重跑前需檢查路徑假設。

## 驗證邊界

單元測試使用合成素材，驗證程式行為，不代表真實辨識準確率。真實評估只有這批三種稀有度卡片；雖然重複卡面與參考分組隔離，仍共用少量截圖、解析度與 UI 條件，不代表不同裝置／壓縮／亮度／遊戲改版均有相同效果。

修改前完整測試為 179 passed、2 skipped；修改後為 **232 passed、2 skipped**（新增 53 項）。略過的 2 項是此 worktree 沒有私有原始 `Test.png` 的既有裁切測試。另已實際執行 `gget-classify` 的單張 Debug 與 144 張批次 CLI，沒有圖片／參考包錯誤，並重新檢查全部 144 張來源及副本 SHA-256，零差異。

尚未驗證 N／R 真實框線、SSP 特殊效果、嚴重遮擋、其他 UI 比例、旋轉或錯位裁切。比例正常也不能證明卡片完整；有遮擋應允許 UNKNOWN。人工標籤後續仍可校正，校正後須保留來源並重算評估。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_card_normalizer.py tests/test_card_classifiers.py tests/test_card_references.py tests/test_card_attributes.py
.venv/Scripts/python.exe -m pytest
```

實測環境為 Python 3.13.16、OpenCV 4.14.0、NumPy 2.5.4、pytest 9.2.0。Context7 沒有完全對應 OpenCV 4.14 的文件，使用 4.13 官方文件查證[遮罩模板匹配](https://github.com/opencv/opencv/blob/4.13.0/doc/tutorials/imgproc/histograms/template_matching/template_matching.markdown)與[直方圖比較](https://github.com/opencv/opencv/blob/4.13.0/doc/tutorials/imgproc/histograms/histogram_comparison/histogram_comparison.markdown)，再以安裝版本測試實際 API。
