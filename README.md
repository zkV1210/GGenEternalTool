# GGET Account Scanner

《SD 鋼彈 G 世代永恆》（SD Gundam G Generation ETERNAL）的**帳號資料擷取與 AI 諮詢工具**。

本專案希望讓玩家不必手動逐台登記機體。工具會將玩家提供的遊戲畫面轉換為可檢查、可修正、可匯出的帳號資料，未來再交由 LLM 協助查詢持有機體、討論配隊、養成資源、交換與抽卡選擇。

目前優先完成**上傳截圖 → 自動定位 → 裁切卡片 → 分類與比對 → 建立玩家資料 → 匯出 JSON** 的最小可運作流程（MVP）。影片自動擷取與模擬器操作留待後續階段。

## 開發狀態總覽

> **目前 Main 可用：** 手動提供 Layout JSON 的單張圖片裁切工具，以及獨立的本地機體 Catalog 原型。自動 Layout Detection 與 Card Classification 已有獨立開發 Branch，但尚未 Merge；不代表 Main 已具備這兩項功能。

| 模組 | 進度 | Branch／整合狀態 |
| --- | --- | --- |
| Video Capture — 影片截圖擷取 | 暫緩 | 尚未納入 MVP |
| Layout Detection — 卡片網格定位 | 開發中 | 獨立 Branch，尚未 Merge |
| Card Slicing — 卡片裁切 | **已完成** | **Main** |
| Card Classification — 稀有度與職能分類 | 開發中 | 獨立 Branch，尚未 Merge |
| Unit Matching — 機體身分比對 | 尚未實作 | 尚未整合 |
| Player Database — 玩家持有資料 | 尚未實作 | 尚未整合 |
| Data Export — 帳號資料匯出 | 尚未實作 | 尚未整合 |

**勾選代表功能已完成，不代表 Branch 已 Merge。** Branch 是否已整合由後面的 Integration TODO 獨立追蹤。目前只有 Card Slicing 勾選完成。

## 整體資料流

```text
玩家提供遊戲畫面
  ├─ MVP：直接上傳機體列表截圖
  └─ 未來：錄影／模擬器畫面 → Video Capture
                         │
                         ▼
                  Layout Detection
               自動定位卡片 → layout.json
                         │
                         ▼
                    Card Slicing
                依 layout.json 裁切圖片
                         │
                         ▼
                 Card Classification
                    稀有度、職能
                         │
                         ▼
                     Unit Matching
              縮小候選範圍 → 比對機體 ID
                         │
                         ▼
                    Player Database
               去重、更新、玩家確認修正
                         │
                         ▼
                      Data Export
                    Inventory JSON
                         │
                         ▼
                 LLM／Skills／MCP（選配）
                 帳號查詢、配隊與養成建議
```

各階段應具有清楚的輸入與輸出，避免將截圖定位、卡片辨識、玩家資料管理與 LLM 問答耦合在一起。前一個模組產生的資料應能獨立驗證，再交給下一個模組使用。

## Module TODO List

### 1. Video Capture — 影片截圖擷取

**狀態：暫緩；MVP 改由玩家直接上傳截圖。**

- [ ] 從錄影自動取得有效的機體列表截圖
- [ ] 辨識列表捲動與畫面切換，排除重複或過渡畫面
- [ ] 將截圖依順序交給 Layout Detection

### 2. Layout Detection — 卡片網格定位

**狀態：已有獨立 Branch 實作中，尚未 Merge。**

- [ ] 使用 OpenCV 偵測列表 UI 錨點（如上方水平白線）
- [ ] 偵測候選卡片邊界，排除背景與機體立繪干擾
- [ ] 推算卡片寬高、排列間距與網格位置
- [ ] 驗證完整卡片，排除遭捲動或 UI 遮擋的區域；MVP 最多處理兩列
- [ ] 產出與現有 Card Slicing 相容的 `layout.json`

### 3. Card Slicing — 卡片裁切

**狀態：已完成，位於 Main；不需要 Merge。**

- [x] 讀取與驗證 Layout JSON，依其幾何座標裁切機體卡片，並提供裁切結果、Overlay 與 Manifest

### 4. Card Classification — 卡片屬性分類

**狀態：已有獨立 Branch 實作中，尚未 Merge。**

- [ ] 統一卡片圖片尺寸並進行必要的影像預處理
- [ ] 依卡片外框與 UI 特徵辨識稀有度（如 UR、SSR、SR）
- [ ] 依圖示辨識職能（攻擊、耐久、支援）
- [ ] 將分類結果與可信度交給 Unit Matching

### 5. Unit Matching — 機體身分比對

**狀態：尚未實作。**

- [ ] 建立完整立繪與機體 ID 的可檢索特徵資料
- [ ] 根據稀有度、職能等資訊縮小候選機體範圍
- [ ] 比對裁切後的卡片局部圖片與完整立繪
- [ ] 輸出 Top-K 候選機體及匹配分數／可信度
- [ ] 將低信心、未知或無法確認的結果交由玩家確認

### 6. Player Database — 玩家持有資料管理

**狀態：尚未實作。**

- [ ] 定義玩家持有機體資料與獨立遊戲 Catalog 的關聯
- [ ] 寫入玩家確認或可信度足夠的辨識結果
- [ ] 記錄突破、SP／SSP、等級等可見養成狀態
- [ ] 合併多張截圖、去除重複項目並支援更新
- [ ] 保留未知欄位、辨識來源與人工修正紀錄

### 7. Data Export — 帳號資料匯出

**狀態：尚未實作。**

- [ ] 定義統一的玩家 Inventory JSON 格式
- [ ] 從 Player Database 匯出可供其他工具使用的 JSON
- [ ] 產生辨識摘要及待確認／異常項目報告
- [ ] 支援其他結構化格式（如 CSV，選配）

## Integration TODO

**目前 Card Slicing 已在 Main，不需要額外合併。** 其他正在開發的模組必須先完成各自的測試，再進行整合。

- [ ] Merge Layout Detection 至 Main
- [ ] 驗證 Layout Detection → Card Slicing 的輸入輸出相容性
- [ ] Merge Card Classification 至 Main
- [ ] 驗證 Card Slicing → Card Classification 的輸入輸出相容性
- [ ] 串接 Unit Matching、Player Database 與 Data Export
- [ ] 完成「上傳截圖 → 匯出 Inventory JSON」端到端測試

## 目前可用：Card Slicing

Main 已實作以**明確提供的 Layout JSON** 處理單張圖片的幾何裁切工具，包括 Layout 載入與驗證、網格展開、矩形／透視裁切、Debug Overlay 及 CLI。

目前的裁切器**不會自行猜測手機比例、卡片位置或排數**；自動偵測是獨立的 Layout Detection 工作。裁切器不修改輸入圖片與 Layout，相同輸入與設定應得到相同結果。

### 安裝與測試

需求為 Python 3.11 以上，建議 Python 3.13。主要依賴 NumPy、OpenCV headless；開發測試使用 pytest。

以下為 Windows PowerShell 指令，假設已安裝 [uv](https://docs.astral.sh/uv/pip/environments/)：

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m pytest
```

虛擬環境、快取及產生的輸出檔案不納入 Git。

### 裁切範例

```powershell
.venv/Scripts/gget-scan.exe path/to/screenshot.png data/profiles/sample_grid.json --output outputs/my_scan
```

`sample_grid.json` 為 **1920×1080 比例的格式示範**，不是通用遊戲座標。使用時需提供與截圖相符的 Layout；有效畫面比例不相符時，現有程式會回報錯誤。

每次請使用新的輸出目錄；現有程式不覆寫既有內容。成功後會產生：

- `card_000_r0_c0.png` 等卡片裁切圖：依逐排順序編號，列、欄及索引從 0 開始。
- `overlay.png`：標示卡片邊界、頂點與編號的檢查圖片。
- `manifest.json`：本次裁切的幾何座標、尺寸、狀態及對應檔名；**不是**玩家 Inventory JSON。

預設採外接矩形裁切；如需四邊形校正，可使用：

```powershell
.venv/Scripts/gget-scan.exe path/to/screenshot.png data/profiles/sample_grid.json --mode perspective --output-size 200 400 --output outputs/my_scan_perspective
```

`--output-size` 可省略，屆時會依對邊長度估算。其他現有選項包括 `--viewport LEFT TOP RIGHT BOTTOM`、`--hide-vertices`、`--hide-indices`、`--hide-row-column` 與 `--hide-grid`。

## 機體 Catalog（既有原型）

專案另有獨立的本地機體識別 Catalog，已包含 Schema、資料查詢與驗證、離線匯入，以及可停止／續跑的公開資料與圖片抓取工具。

Catalog 儲存的是**遊戲內機體的參考資料**，不是玩家實際持有的 Inventory。後續 Unit Matching 應查詢 Catalog 中的機體 ID、稀有度、職能及圖片資訊，Player Database 則只記錄玩家持有與養成狀態。

Catalog 的使用方式、抓取流程、來源限制與資料格式請參考 [docs/catalog.md](docs/catalog.md)。

## 掃描與資料設計原則

### 快速掃描（MVP）

玩家上傳機體列表截圖即可使用，不要求登入遊戲帳號或讓工具操作手機。未來 Layout Detection 完成並整合後，可自動處理不同解析度與畫面配置。

機體辨識採逐步縮小候選範圍的方式：先判斷稀有度與職能，再從 Catalog 中找出最可能的機體 ID／版本。由於目前 Catalog 的圖片來源是**完整立繪**，而遊戲卡片使用局部裁切，Unit Matching 需處理裁切、縮放及 UI 覆蓋造成的差異。

不可靠的結果應保留候選與可信度，供玩家確認，不應在缺乏證據時強制選定機體。

### 詳細掃描（後續規劃）

未來可考慮透過 Android 模擬器與 ADB，依序開啟機體詳情頁並截圖，以取得更完整的突破數、機體等級、武裝及技能等資訊。此模式需要處理畫面載入、翻頁錯誤、重複擷取、停止／恢復，以及遊戲對自動化與模擬器的限制。

模擬器自動掃描是選配功能，不是 MVP 的必要條件。

### 遊戲資料與玩家資料分離

- **Game Catalog：** 機體 ID、名稱、版本、稀有度、職能、性能、標籤與參考圖片等。
- **Player Inventory：** 玩家是否持有、突破、SP／SSP、等級、武裝與技能養成等狀態。
- **辨識紀錄：** 來源截圖、識別可信度、玩家確認及未確定欄位。

SP／SSP 是機體養成狀態，**不應直接視為獨立的原始稀有度**。截圖無法確認的欄位使用 `null`／`unknown`，不可預設為 0、滿突或滿等。

## LLM 帳號顧問（後續規劃）

當玩家 Inventory JSON 可穩定產出後，便能透過 ChatGPT 或其他 LLM 工具詢問配隊、養成、資源交換或抽卡建議，例如「依照我現在持有的機體和駕駛，該優先強化哪個隊伍？」

初期優先使用**可攜式 JSON 搭配既有 LLM 對話工具**，未來再評估 BYOK（玩家自行提供 API Key）、Skills 和 MCP 等整合方式。

推薦內容應盡可能根據可查證的遊戲資料、攻略來源與更新日期；精確數值與規則檢查應由程式完成。若 Agent 要修改玩家 Inventory，必須先顯示變更、取得玩家確認，並保留修改紀錄。

## 文件索引

- [Main baseline 與 Worktree 協作](docs/baseline.md)：版本基準、驗證結果、分支與工作樹協作規範。
- [Catalog 文件](docs/catalog.md)：機體參考資料、Schema、查詢、匯入與公開資料抓取規則。
- [架構與幾何規則](docs/architecture.md)：Layout Schema、Resolver、Cropper、座標與錯誤處理定義。
- [後續技術規劃](docs/roadmap.md)：GUI 校準、辨識、Inventory、Capture／Tracking 的詳細規劃。
- [測試資料說明](tests/fixtures/README.md)：合成測試資料與測試素材管理原則。

## 長期方向

核心辨識流程完成後，預計逐步擴充駕駛、支援者、帳號資源、OCR、跨裝置掃描、模擬器詳情頁、增量更新，以及機體性能與攻略知識庫。遊戲攻略可整合中文、日文網站與影音來源，並保留來源連結和日期。

進一步可提供可重現的配隊合法性檢查、養成收益比較與數值分析，再交由 LLM 進行自然語言解釋。

## 開發原則

- **模組解耦：** 定位、裁切、分類、比對、資料管理與匯出各自保持明確職責。
- **先驗證再整合：** 各 Branch 完成單元測試與輸出檢查後，才 Merge 回 Main；不要把「已有 Branch」等同於「已完成」。
- **最小必要實作：** 優先完成固定截圖的 MVP，避免為未確認的情境過度設計。
- **可追溯與可修正：** 保留辨識來源、可信度、未知狀態與玩家人工修正能力。
- **尊重資料權利：** 不以讀取遊戲記憶體或攔截遊戲封包為前提；遊戲圖片及第三方攻略內容應遵守授權與使用條款。

完成一項功能後再更新對應 TODO，並同步確認 Integration TODO 是否達成；**不要只因程式已經存在於獨立 Branch，就提前勾選完成。**
