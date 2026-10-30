# main baseline 與 worktree 協作

此文件記錄 2026-10-30 準備的 baseline 範圍與驗證結果。這次整理尚待使用者允許 Commit；僅修改 `.gitignore` 或保留未提交檔案，不會讓新 worktree 取得這些內容。必須先將經確認的內容 Commit 到 `main`，再從該 Commit 建立功能分支。

## baseline 內容

| 路徑 | 已實作內容 |
| --- | --- |
| `pyproject.toml` | Python 套件、依賴、pytest 與 `gget-scan` CLI 設定 |
| `src/gget_scanner/config/` | Layout Schema v1、不可變資料模型與嚴格 JSON Loader |
| `src/gget_scanner/image/` | 0～10000 座標解析、比例與 Viewport 驗證、網格展開、外接矩形／透視裁切、Overlay |
| `src/gget_scanner/pipeline/` | 單張圖片流程與 CLI；輸出卡片、Overlay 及幾何 manifest，避免覆寫 |
| `src/gget_scanner/catalog/` | 機體識別 Schema v1、穩定 UUID、查詢、JSON 載入／原子儲存、圖片路徑／解碼／雜湊／尺寸驗證 |
| `scripts/catalog_import/` | Soshage 列表／詳情頁解析、使用者確認的稀有度與定位代碼、離線匯入、衝突紀錄、圖片修復、限速及 robots 檢查、可續跑抓取與 heartbeat |
| `data/profiles/` | 格式示範 Layout，以及本機 2388×1668 截圖的手動 8×2 Layout |
| `data/catalog/units.json` | 使用者選擇納入的 1,321 筆 Catalog 快照；圖片只留本機 |
| `tests/` | 合成圖片、Schema／幾何／CLI、Catalog／匯入／HTTP／續跑測試，以及可略過的私有截圖驗證 |
| `README.md`、`docs/`、`.gitignore` | 使用說明、架構、來源限制、後續規劃與本機產物排除規則 |

目前未實作 GUI 校準器、自動 Layout 偵測、機體圖片辨識、OCR、玩家 Inventory、影片掃描、ADB 控制、跨畫面 Tracking／去重、LLM 整合或性能資料庫。

## 已執行的驗證

- Python 3.13.16、OpenCV 4.14.0、NumPy 2.5.4、pytest 9.2.0；其他版本尚未實測。
- 完整 pytest：**181 項通過**。其中私有 `Test.png` 存在，兩種裁切模式均參與測試；沒有該圖的環境會略過對應 2 項。HTTP 與抓取測試使用假回應，不需網路。
- 將 43 個 baseline 候選檔案複製到獨立目錄，不帶入本機圖片、快取或環境；確認 Python 從副本載入程式後執行 pytest，結果為 **179 項通過、2 項私有截圖測試略過**。此項使用現有環境的依賴測試來源副本，不等同已建立 worktree 或在全新機器完成安裝。
- `python -m scripts.catalog_import validate`：退出碼 0，回傳空問題清單。重新確認本機 1,321 筆機體的圖片紀錄；對應 1,209 個實體檔案，共 111,650,528 bytes，部分紀錄共用圖片。
- Catalog 驗證前後 SHA-256 相同，沒有改寫 JSON 或圖片。依賴相容性檢查通過。
- 本次未啟動真實網路抓取，完整抓取的完成狀態依據現有 checkpoint／log 與本機資料驗證，不代表重新執行過抓取。

## Git 與本機資料邊界

下列內容保留在本機並由 `.gitignore` 排除：

- `AGENTS.md`：依使用者要求只留本機，不會自動出現在新 worktree。
- `tests/fixtures/private/` 與根目錄 `Test.png`：遊戲截圖及其他私有測試資料。
- `data/local_assets/`：下載圖片、HTML、抓取 checkpoint、log、錯誤與隔離備份。
- `outputs/`：裁切結果、Overlay、研究備份、測試與驗證產物。
- `.venv/`、`.uv-cache/`、Python／pytest 快取、egg-info、build／dist：環境與可重建產物。
- `.worktrees/`：若使用專案內的 worktree 容器，主工作目錄不會把它當作來源檔案。
- `.env` 與 `.env.*`：本機環境設定；`.env.example` 與 `.env.template` 可作為公開範例。

`data/catalog/units.json` **不忽略**，保留本次使用者選定的完整 JSON；不為了讓新環境看起來驗證成功而清除 `local_path`、改寫 downloaded 狀態或製造空 Catalog。新環境若需要圖片，必須另外提供本機圖片資料，並重新執行 Validator。

## Commit 後建立 worktree

以下指令為後續操作範例，本次不自動建立 worktree。先取得使用者對 baseline Commit 的允許，完成提交並確認 `main` 的 HEAD 已是該 baseline，再於專案根目錄執行：

```powershell
git worktree add -b feature/layout-calibration .worktrees/layout-calibration main
git worktree add -b feature/recognition .worktrees/recognition main
git worktree list
```

每項功能使用不同分支；不要讓兩個 worktree 同時檢出 `main`，也不要使用 `--force` 繞過分支使用中的檢查。各 worktree 有自己的工作檔案、HEAD 與 index，但共用 Git 物件與一般分支參照。參考 [Git 官方 worktree 說明](https://git-scm.com/docs/git-worktree)。

新 worktree 不會自動複製未提交或被忽略的檔案。每個功能環境需另外準備：

1. **本機規範**：將根工作目錄的 `AGENTS.md` 複製到新 worktree；仍保持忽略，並向該工作對話說明本次檔案責任與 Commit 授權。
2. **獨立環境**：在該 worktree 建立自己的 `.venv`，依 README 安裝 `.[dev]`。不要共用原工作目錄的 editable install，否則 Python 可能載入另一份來源碼。
3. **可選測試截圖**：需要真實圖片測試才複製 `tests/fixtures/private/Test.png`；一般合成測試不需要。
4. **Catalog 圖片**：辨識功能需要圖片時，保留相同相對路徑，另外複製本機 `data/local_assets/images/`。只讀查詢原資料時也可明確傳入原工作目錄作為 root；不要把多個寫入程序指向同一個 root，或以硬連結共用會被修改的檔案。
5. **抓取續跑**：僅複製圖片不包含原 checkpoint；需要延續同一工作時，應先協調唯一寫入者與一致的 Catalog／快取快照。不要為了準備 worktree 自動啟動抓取。

每個 Agent 只在分配的 worktree 與檔案範圍工作。整合回 `main` 前先檢查各分支 diff 與測試；merge、rebase、Push 與共用 Git 狀態操作由指定者協調，不能視為建立 worktree 就已授權。
