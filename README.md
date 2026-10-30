# GGET Account Scanner

《SD 鋼彈 G 世代永恆》（SD Gundam G Generation ETERNAL）的**帳號資料擷取與 AI 諮詢工具**，目前已建立 Layout 裁切、本地 Catalog 與卡片 UI 屬性辨識原型。

本專案希望讓玩家不必手動逐台登記機體：先把遊戲畫面轉換成可檢查、可修改的帳號資料，再交給 LLM，根據實際持有內容討論配隊、養成資源、交換與抽卡選擇。

> **專案狀態：幾何處理、本地 Catalog 與屬性辨識原型。** 已實作 Layout JSON 載入與驗證、網格展開、矩形／透視裁切、Debug Overlay 及 CLI，以及 Catalog Schema、查詢、驗證、離線匯入與可續跑抓取工具。已裁切卡片可另外進行尺寸標準化、粗邊框 Lab 參考比對（SR／SSR／UR）與職能徽章 HSV／模板驗證。機體立繪匹配、OCR、Inventory JSON、模擬器控制與 LLM 功能尚未實作。

## 目前可用：Layout 與單張圖片裁切

程式只按照明確提供的 Layout 處理單張圖片，不會猜測手機比例、卡片位置或排數。相同圖片與設定會得到相同結果；輸入圖片與 Layout 不會被修改。

### 安裝與測試

需要 Python 3.11 以上；建議使用 Python 3.13。依賴為 NumPy 與 OpenCV headless，開發測試使用 pytest。以下為 Windows PowerShell 指令，使用已安裝的 [uv](https://docs.astral.sh/uv/pip/environments/) 建立環境：

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m pytest
```

完成安裝後即可執行上述測試指令。虛擬環境、快取與輸出不納入 Git。

### 裁切與檢查位置

```powershell
.venv/Scripts/gget-scan.exe path/to/screenshot.png data/profiles/sample_grid.json --output outputs/my_scan
```

`sample_grid.json` 是 **1920×1080 比例的格式示範**，不是通用遊戲座標。請依實際圖片調整 JSON；有效畫面比例不同時程式會明確報錯。

每次請使用新的輸出目錄，程式不會覆寫既有內容。成功後會得到：

- `card_000_r0_c0.png` 等卡片圖片，按逐排順序編號，行列及索引皆從 0 開始。
- `overlay.png`：卡片邊界、頂點、索引與行列編號。
- `manifest.json`：本次幾何裁切的座標、尺寸、狀態與檔名；這不是未來的 Inventory 匯出格式。

預設採外接矩形裁切。需要四邊形校正時使用 `--mode perspective`，可另以 `--output-size 200 400` 指定寬、高；未指定時依對邊長度估算。其他選項包含 `--viewport LEFT TOP RIGHT BOTTOM`、`--hide-vertices`、`--hide-indices`、`--hide-row-column`、`--hide-grid`。

### 本機真實截圖

本機截圖放在 `tests/fixtures/private/Test.png`，已加入忽略規則，不納入 Git。`data/profiles/test_screenshot.json` 是這張 **2388×1668** 截圖的手動校準設定，只選取前兩排、每排 8 張卡片；不是自動偵測的結果，也不保證適用其他截圖。

```powershell
.venv/Scripts/gget-scan.exe tests/fixtures/private/Test.png data/profiles/test_screenshot.json --output outputs/my_test_bbox
.venv/Scripts/gget-scan.exe tests/fixtures/private/Test.png data/profiles/test_screenshot.json --mode perspective --output outputs/my_test_perspective
```

自動測試使用程式產生的合成圖片，不需要遊戲素材。若本機私有截圖存在，會額外執行真實圖片裁切測試；沒有圖片則略過該項。

### 文件入口

- [main baseline 與 worktree 協作](docs/baseline.md)：確認此次待提交內容、驗證結果及本機資料邊界時閱讀；baseline Commit 獲准完成後，依此建立各功能的獨立分支與環境。
- [本地機體識別 Catalog](docs/catalog.md)：建立或查詢機體 JSON 時閱讀，包含掛機啟動指令、英文進度 log、停止與續跑規則、圖片對應、離線匯入及來源限制；與 Layout／Cropper 獨立。
- [卡片屬性辨識](docs/recognition.md)：串接裁切結果、執行單張／批次分類、查看 Debug、加入稀有度樣本或實際職能模板時閱讀；包含參數、UNKNOWN／嚴格篩選規則、重新分類的本機測資及實測結果。
- [架構與幾何規則](docs/architecture.md)：修改 Schema、Resolver、Cropper 或串接 Python API 前閱讀，包含座標、像素邊界、驗證及錯誤處理的完整定義。
- [後續開發方向](docs/roadmap.md)：規劃 GUI 校準、辨識、Inventory 與 Capture／Tracking 時閱讀；這些未實作模組必須沿用目前的 Layout 邊界與職責分工。
- [測試資料說明](tests/fixtures/README.md)：新增合成測試或本機截圖時閱讀，說明哪些資料可進 Git、哪些只保留在本機。

## 預計工作流程

```text
玩家提供資料
  ├─ 快速掃描：手機／模擬器的機體列表截圖（未來可支援錄影）
  └─ 詳細掃描：模擬器逐台開啟機體詳情並擷取畫面（未來規劃）
                  ↓
       影像預處理與介面定位
                  ↓
       卡片／資訊區域裁切與辨識
                  ↓
       機體 ID 比對、狀態擷取、去重與檢查
                  ↓
          玩家確認／修正結果
                  ↓
          結構化帳號 JSON
                  ↓
       LLM + Skills／MCP（可選）
                  ↓
       帳號查詢、配隊與養成建議
```

## 1. 從遊戲畫面建立帳號資料

核心想法是**將「取得畫面」與「理解畫面」分開**。不同玩家可以用不同方式提供資料，但最後都經過相同的辨識、驗證與匯出流程。

### 快速掃描（優先開發）

玩家上傳手機上的**機體列表截圖**，不需要登入帳號，也不需要讓工具操作遊戲。初期假設使用固定版面圖片；未來再逐步支援不同螢幕比例、介面配置與連續錄影。

掃描器預期會：

1. 使用 OpenCV 等工具進行影像預處理、辨識列表位置，並裁切每張**長方形機體卡片**。
2. 從卡片中分離機體插畫、名稱、類型與其他可見狀態；優先利用插畫區域與參考圖片庫比對，確認對應的**機體 ID／版本**，必要時搭配文字或圖示辨識。
3. 對重複截圖、難以辨識或被 UI 遮擋的項目進行標記；呈現候選結果供玩家確認，而不是強制猜測。
4. 匯出目前可靠取得的持有資訊。列表上看不到的突破、武裝或技能等級應保留為**未知**，不能預設已練滿。

初期目標以 **UR、SSR 及 SP／SSP 強化狀態**相關機體為主；SP／SSP 是需要記錄的養成狀態，不應直接當成獨立稀有度。

### 詳細掃描（後續規劃）

對願意使用 Android 模擬器的玩家，未來考慮透過 ADB 等方式，**自動切換機體詳情頁並依序截圖**，再沿用上述辨識流程擷取更完整的資訊，例如突破數、機體等級、武裝等級及其他可見養成狀態。

此模式需額外處理畫面載入、翻頁失敗、重複擷取、停止與恢復，以及遊戲對模擬器／自動化操作的相關限制。**模擬器掃描是可選功能，不是使用本工具的必要條件。**

### 共用輸出格式

兩種掃描方式都應產出一致的 **JSON 帳號資料格式**，並允許玩家人工修正。資料需區分：

- **遊戲資料**：機體 ID、名稱、版本、類型、性能及標籤等，來自獨立的機體資料庫。
- **玩家資料**：實際持有、突破、SP／SSP、等級、武裝與技能養成狀態等，來自掃描或手動輸入。
- **可信度與來源**：哪些欄位已辨識、哪些經玩家確認、哪些尚未得知，以及資料來自哪次掃描。

未讀取到的欄位以 `null`／`unknown` 表示，不以「0」或「滿等」代替。掃描結果應可重新匯入、校正及更新，並在未來支援 CSV 匯出。

## 2. LLM 帳號顧問（後續規劃）

玩家可將匯出的帳號 JSON 放入 ChatGPT 專案或其他 LLM 工具，提出自然語言問題，例如：

- 以我目前持有的機體與駕駛，適合組哪些隊伍？
- 現在的突破／交換資源應優先投入哪台機體？
- 新卡池對我的帳號有哪些補強價值？

初期以**可攜式 JSON + 現有 LLM 對話工具**為主，之後再考慮 BYOK（玩家自行提供 API Key）的整合介面。

未來可透過 **Skills** 定義帳號分析、資料驗證與推薦流程，並以 **MCP／其他工具介面**讓 Agent 查詢機體資料庫、攻略來源及玩家資料。LLM 應以可查證的資料為依據；需要精確計算或合法性檢查時，交由程式處理，而非單靠模型猜測。

若 Agent 要**修改玩家帳號資料**，應先提出變更並取得玩家確認，保留可追溯的修改紀錄；分析建議本身不應直接改寫持有狀態。

## 3. 後續方向

- 擴充辨識支援：不同解析度與比例、OCR、錄影掃描、模擬器詳情頁。
- 擴充帳號資料：駕駛、支援者、資源與多次掃描的增量更新。
- 建立機體性能與攻略知識庫，整合日文網站及中文 YouTube 攻略，保留來源與日期。
- 加入可重現的配隊檢查、養成收益比較與數值分析，再與 LLM 顧問整合。

## 開發原則

以**辨識可靠、資料可人工確認、模組可替換**為優先；先完成固定圖片的最小可運作流程，再逐步擴充。專案不以讀取遊戲記憶體或攔截遊戲封包為前提。遊戲圖片與第三方攻略內容應尊重原作者授權及使用條款。
