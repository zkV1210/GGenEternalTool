# Local Unit Identity Catalog

目前已實作 Catalog Schema v1、Loader、Validator、Soshage 列表／詳情頁解析、離線匯入及可續跑的完整清單抓取 CLI。Layout／Cropper 核心未修改，不包含 Recognition、Inventory、SP／SSP 養成狀態或數值資料庫。

依使用者後續指示，`crawl` 會逐台嘗試保存公開機體資料與圖片，使用明確 User-Agent、robots 檢查、隨機間隔及失敗停止規則，不提供忽略存取限制的參數。HTTP 200 或 robots 未禁止不代表圖片再散布授權；下載圖片與快取僅保留本地，不提交 Git。

## 掛機啟動與續跑

在專案根目錄的 Terminal 手動執行：

```powershell
.venv/Scripts/python.exe -u -m scripts.catalog_import crawl
```

預設一次處理整份公開列表，包含嘗試下載 artwork 圖片，**沒有 100 筆或 30 分鐘上限**。不會在清單跑完後無限重新開始。每個請求之間隨機等待 6～9 秒，逾時 20 秒、最多重試 2 次；速度取決於網路與來源回應，不保證每半小時恰好 100 台。

Terminal 全英文，每 15 秒輸出 RUNNING 狀態，等待與網路讀取期間也會持續顯示。每台完成輸出 OK，包含清單位置、成功／略過／失敗數與圖片已驗證數。時間標示為 UTC+08:00。完整 log 位於 `data/local_assets/cache/crawl/crawl.log`，錯誤另存 `errors.jsonl`。

```text
2026-10-30 04:00:00 +08:00 | QUEUE | total=1321 | images=enabled
2026-10-30 04:00:15 +08:00 | RUNNING | 1/1321 | success=0 skipped=0 failed=0 images=0 | unit=1001000100 | fetching or waiting
2026-10-30 04:00:20 +08:00 | OK | 1/1321 | unit=1001000100 | success=1 skipped=0 failed=0 images=1
```

每完成一台就原子儲存 Catalog 與 `job.json`。`Ctrl+C` 安全停止；重新執行同一指令會使用已固定的列表快照與頁面快取，檢查 Catalog 及本地圖片後略過已完成項目。檔案遺失或圖片雜湊不符時會重新處理，不只相信 checkpoint 的 completed 清單。圖片通過解碼與雜湊驗證後才寫入 `local_path`、`downloaded` 狀態及尺寸，之後可用 `Catalog.reference_paths()` 取得本地檔案。

停止條件：清單完成、Ctrl+C、401／403／404／429／重新導向、robots 禁止或無法理解、來源結構／身分矛盾、未知稀有度／定位代碼、來源衝突、磁碟或 log 寫入失敗；暫時性網路錯誤／部分 5xx 在重試耗盡後可跳過，連續三台失敗則停止。單台失敗會保留原始 URL 與錯誤。圖片回應無法解碼時停止，避免把來源異常當成成功。

退出碼：`0` 本次目標清單全部完成；`1` 有未完成或錯誤；`130` 使用者中斷；`2` 命令或環境無法使用。資料與圖片的完成以本次固定快照為範圍，不宣稱涵蓋遊戲全部機體。

可選參數：

```powershell
# 只抓識別資料與圖片 URL
.venv/Scripts/python.exe -u -m scripts.catalog_import crawl --no-images

# 自行限制此次待處理筆數或執行時間（預設皆不限）
.venv/Scripts/python.exe -u -m scripts.catalog_import crawl --limit 100 --max-minutes 30

# 重新取得列表，保留既有 Catalog／圖片並比對；舊 job 另存快照
.venv/Scripts/python.exe -u -m scripts.catalog_import crawl --refresh-index
```

`--max-minutes` 在每台處理前檢查，不強制中斷正在處理的單台請求。`--index-html PATH` 可讓新工作使用手動保存的公開列表 HTML；已存在 job 時須搭配 `--refresh-index`。`--root PATH` 指定資料輸出根目錄。`--min-delay`／`--max-delay` 可調整等待範圍，但不得短於 robots 的要求。

同一輸出目錄只允許一個 crawl 程序，使用作業系統檔案鎖；異常關閉後鎖會釋放，下次可續跑。請勿同時執行離線匯入或手動改寫 Catalog。

### 完整性與歸零基準

公開列表 HTML 內嵌的 JSON 陣列曾實際讀到 **1,321 個唯一來源 ID**：UR 123、SSR 378、SR 382、R 332、N 106。抓取程式直接解析這個陣列，不呼叫內嵌 `data-url` 所示的 API、不猜編號，也不只讀畫面上少數連結。每個 ID 對應的詳情頁仍須驗證名稱、代碼與圖片對應。網站更新後的筆數可能不同；列表本身是否涵蓋遊戲全機體仍待確認。

依使用者要求，正式掛機前曾將 27 筆 Catalog、一張測試圖片及快取移到 `outputs/catalog-reset-20261030-27fa43ba/`，保留 Catalog SHA-256 與檔案數／大小紀錄，再從空 Catalog 開始抓取。這是先前的歸零紀錄，不是目前的資料狀態；不影響 Layout profiles 或測試資料。下列早期實驗所述的快取若已隨歸零搬移，位於該備份的 `local_assets/cache/` 之下。

2026-10-30 baseline 檢查時，`job.json` 與 log 顯示該次固定清單已於 **2026-10-30 11:21:47（Asia/Taipei）**完成：1,321 台成功、0 台失敗，1,321 筆圖片紀錄為 downloaded，對應 1,209 個實體圖片檔。已重新執行本機 Validator，所有圖片均可解碼，SHA-256 與尺寸符合紀錄；檢查過程未重新抓取網路資料，也未修改 Catalog。這證明本機檔案符合該次清單快照，不代表網站或遊戲之後不會變動，也不是對每張圖片機體身分的人工複核。

使用者已選擇將目前 `data/catalog/units.json` 納入 main baseline 候選內容，圖片與快取繼續忽略。JSON 中的 downloaded 狀態描述建立快照時的本機驗證結果；新 clone／worktree 沒有圖片時，Validator 會回報缺失，不應把狀態欄位視為新環境已具備圖片的證明。資料使用與 worktree 準備見 [baseline.md](baseline.md)。

## 來源研究與限制

2026-10-30 以明確研究用 User-Agent 唯讀檢查：

| 來源 | 觀察與決策 |
| --- | --- |
| [Soshage robots.txt](https://soshage.com/robots.txt) | `User-agent: *`、空白 `Disallow:`，明示允許爬取。公開 zh-TW 詳情 HTML 同時含主機體資料及圖片標記，可在不執行 JavaScript 的情況下解析。 |
| [Soshage About](https://soshage.com/gget/zh-TW/about)、[Privacy Policy](https://soshage.com/gget/zh-TW/privacy-policy) | 已閱讀網站連結的政策；未找到明確的圖片自動下載／再散布授權或文件化 API。來源 ID 不宣稱為官方遊戲 ID。 |
| [圖片主機 robots.txt](https://img.kusoge.xyz/robots.txt) | 先前只見註解形式的 content-signal 說明，沒有作用中的限制規則。程式依標準 robots 規則處理非空的純註解檔；空回應、HTML 或無法理解的指令則停止。這不等於圖片再散布授權。 |
| [GGenDB robots.txt](https://ggendb.up.railway.app/robots.txt) | 禁止 `/api/`、`/static/` 等路徑；未呼叫其 API，也未下載被禁止的程式檔。MVP 不採用。 |
| [Athena](https://athena-gget.com/) | `/robots.txt` 回傳首頁 HTML；網站說明有資料缺漏，首頁亦顯示免費版與密碼解鎖介面。許可不明，MVP 不採用，不接觸受限內容。 |

歸零前已驗證 27 筆公開頁面，另單張實測[鋼彈 (EX)](https://soshage.com/gget/zh-TW/unit/1001000150)的 WebP 下載／解碼成功（936×803，202,094 bytes）。來源 `1001000150` 與圖片資產 `g0010u00150` 是不同識別值；解析器交叉檢查 URL 的來源 ID、頁面主標題、主機體內嵌 ID／名稱／icon、主圖片 URL 及 alt，拒絕不一致，不自行拼出未出現在頁面上的圖片 URL。

新增的 6 台依序為吉翁克 (EX)、夏亞專用薩克Ⅱ (THE ORIGIN版)(EX)、畢格‧朗格 (EX)、鋼彈Ez8 (EX)、古夫特裝型 (EX)、達勒，使用 robots 檢查及 8～15 秒隨機間隔。原始頁面與代碼觀察結果保存在本地忽略目錄 `data/local_assets/cache/soshage-code-review-20261030/`。達勒頁面包含武裝用的 `unit:{unit_id:...}`；解析器已限制主機體必須以 `unit:{id:...}` 起始，避免誤選武裝資料，並加入合成回歸測試。

依使用者要求，另從公開列表中可解析且排除既有 7 筆的 44 個實際連結，隨機抽取 20 筆，仍使用 robots 檢查及 8～15 秒間隔。抽樣 seed、候選數、選定 URL、原始 HTML、離線匯入 manifest 與標準化觀察結果保存在 `data/local_assets/cache/soshage-random20-20261030/`。本次 20 筆皆為 UR，定位為攻擊 8／耐久 6／支援 6；這是上述連結範圍的隨機抽樣，不代表全遊戲或各稀有度的均衡抽樣。首次匯入新增 20 筆，重跑 20 筆均 unchanged，無解析錯誤或來源衝突，既有 7 筆未改動。

本次保留兩筆同名「比基納‧澤拉 (鋼彈型)」，來源 ID 分別為 `1157000201`、`1157000202`；來源 ID 不同，沒有按名稱合併。兩者在遊戲中是否為可持有的不同版本／型態仍待確認，不因來源列出就推論玩家可分別持有。

使用者於 2026-10-30 確認下列映射，解析器已採用；同時保留來源原始代碼。圖示 alt 即使只有 `Rarity`／`Role`，也能依已確認的代碼標準化；未列出的代碼仍為 `null`，不向外推測。

| 稀有度代碼 | 標準值 | 定位代碼 | 標準值 |
| --- | --- | --- | --- |
| 5 | UR | 1 | 攻擊 |
| 4 | SSR | 2 | 耐久 |
| 3 | SR | 3 | 支援 |
| 2 | R | | |
| 1 | N | | |

已補齊的欄位若與來源明示的稀有度文字矛盾，解析器會拒絕該頁。既有 Catalog 僅在原始代碼與其他識別資料一致時補上空白 rarity／role，並記錄 `metadata_enrichment` 的新舊資料；不覆蓋非空的衝突值。更新前的 7 台資料已備份於忽略目錄 `data/local_assets/cache/units-before-confirmed-mapping-20261030.json`。

解析器依賴已觀察到的 Soshage HTML 與內嵌純量欄位。主機體的欄位會依序讀取完整字串／數字等純量，避免描述內的 `stats:{` 或 `,role:1,` 被誤認成欄位。網站改版會明確報錯，不以 `eval`、執行腳本或猜測補資料。整頁可能含數值與武裝，但輸出只保留識別欄位；原始 HTML 只作本地快取，不提交 Git。來源快照與圖片不代表遊戲目前完整資料。

## 檔案與資料流

```text
使用者合法取得的 HTML／圖片 + manifest.json
    → scripts/catalog_import/importer.py：讀取本地檔案
    → scripts/catalog_import/soshage.py：純解析，無 I/O
    → 衝突檢查、圖片解碼／SHA-256 驗證
    → data/catalog/units.json
    → src/gget_scanner/catalog/loader.py → 未來 Recognition
```

- `catalog/models.py`：不可變的 Unit、UnitSource、UnitImage 與 Catalog 資料類別，及穩定 ID 產生規則。
- `catalog/loader.py`：嚴格載入／儲存 Schema v1；拒絕未知／缺少欄位、重複 JSON key、重複機體或來源識別、非法型別與路徑。輸出使用同目錄暫存檔、flush／fsync 及原子替換。
- `catalog/validator.py`：列出缺失欄位，檢查本地檔案可讀取、可解碼、雜湊與尺寸一致。它不能只憑圖片判斷機體身份正確。
- `scripts/catalog_import/http.py`：限速、重試、robots 與存取限制檢查；crawl 只啟用已解析索引與頁面所得的 URL，離線 CLI 不使用它。
- `scripts/catalog_import/index.py`：只從公開 HTML 內嵌 JSON 提取來源 ID、名稱、稀有度與定位代碼，不把完整數值資料寫入 Catalog。
- `scripts/catalog_import/crawl.py`：英文 heartbeat、完整清單、圖片下載／驗證、checkpoint 與安全停止；所有網路工作都在手動執行 crawl 後才開始。

圖片路徑以 `--root` 指定的專案根目錄為基準，使用相對 POSIX 路徑。圖片存於 `data/local_assets/images/<sha256>.<格式>`；PNG、WebP、JPEG 保留對應副檔名，其他可解碼格式以 `.img` 保存。快取與錯誤／衝突紀錄位於 `data/local_assets/cache/`。整個 `data/local_assets/` 已加入 `.gitignore`。

## Schema v1

頂層為 `{"schema_version": 1, "units": [...]}`。所有欄位都必須存在；未知欄位值用 `null`，不省略欄位。空的 `images` 允許保存不完整紀錄，但 Validator 會回報缺失。

| 模型／欄位 | 意義 |
| --- | --- |
| Unit `unit_id` | 專案自己的 canonical UUID 字串。初次匯入以 UUIDv5、`NAMESPACE_URL`、`urn:gget-scanner:unit:<來源>:<來源ID>` 產生，不依名稱或網站排序。 |
| `name`、`language`、`rarity`、`variant`、`role` | 名稱、語言、基礎稀有度、來源明示版本、定位。皆可為 `null`；稀有度限 N／R／SR／SSR／UR。版本目前只擷取名稱末尾明示的 `(EX)`／`（EX）`，不推論其他版本。 |
| `sources[]` | `source`、字串 `source_id`、`page_url`、附時區的 ISO `retrieved_at`、可為 null 的 `rarity_code`／`role_code`。離線匯入的時間代表讀取本地快照的時間，不等於網站內容更新時間。 |
| `images[]` | `kind`、`source_url`、`local_path`、`status`、`sha256`、`width`、`height`、`error`。未知值為 null。 |
| 圖片 `kind` | `artwork`、`thumbnail`、`game_list_reference`，預留遊戲列表專用參考圖；Soshage 匯入目前只建立 artwork。 |
| 圖片 `status` | `not_downloaded`、`downloaded`、`failed`、`missing`、`invalid`。`downloaded` 代表已驗證的本地檔案，也包含手動提供的檔案，必須同時具有路徑、SHA-256、正整數尺寸且無錯誤。 |

同名不同來源 ID 保持獨立。相同來源 ID 若已在 Catalog 對應既有 `unit_id`，沿用既有對應；不強制重新產生。不同來源不按名稱自動合併。SP／SSP 與玩家持有狀態不屬於本 Schema。

## 離線匯入

在專案根目錄執行，沿用 README 已安裝的 `.venv`。先將**有權使用的** HTML 與圖片放在忽略目錄，例如：

```text
data/local_assets/cache/manual/
    manifest.json
    1001000150.html
    reference.webp
```

manifest 為陣列，每筆指定來源頁面與本地快照；檔案路徑相對於 manifest 所在目錄，不接受絕對路徑或 `..`。`local_images` 可省略；若提供，其 URL 必須與該頁解析出的圖片 URL 完全一致：

```json
[
  {
    "page_url": "https://soshage.com/gget/zh-TW/unit/1001000150",
    "html_path": "1001000150.html",
    "local_images": {
      "https://img.kusoge.xyz/ggenet/profile/ub_g0010u00150.webp": "reference.webp"
    }
  }
]
```

只有 HTML 時省略 `local_images`，圖片保留來源 URL 與 `not_downloaded` 狀態。

```powershell
.venv/Scripts/python.exe -m scripts.catalog_import import data/local_assets/cache/manual/manifest.json --limit 15
.venv/Scripts/python.exe -m scripts.catalog_import validate
```

`--limit` 是最多處理的 manifest 筆數，預設 15，不是保證成功筆數；**這是本地檔案數量，不會觸發網路請求**。`--root PATH` 可指定另一個輸出根目錄；Loader 的圖片根目錄也必須使用相同位置。

CLI 回報 processed／added／updated／unchanged／conflicts／errors／validation_issues。退出碼 `0` 表示本次沒有錯誤、衝突或不完整紀錄；`1` 表示有這些問題，但可能已保存有效或不完整紀錄；`2` 表示命令或整份輸入無法使用。不要只看是否產生 JSON 就判定匯入完成。若沒有任何新增／更新，既有 JSON 不重寫；全數解析失敗時不建立空 Catalog。

Catalog 快照與本機產物（圖片、測試輸出與快取受 Git 忽略，其他工作區不一定存在）：

- `data/catalog/units.json`：目前為已完成固定清單抓取的 1,321 筆快照，使用者已選擇納入 baseline 候選內容；先前 27 筆與圖片測試檔仍保留於前述 outputs 備份。
- `outputs/catalog-demo-20261030/data/catalog/units.json`：15 台**合成**機體與各自的合成 WebP 圖片，不是遊戲機體資料。已執行首次匯入及重跑，第二次 15 筆皆 unchanged，JSON 與圖片保持不變。

可用合成產物再次試跑完整離線流程：

```powershell
.venv/Scripts/python.exe -m scripts.catalog_import import outputs/catalog-demo-20261030/輸入/manifest.json --root outputs/catalog-demo-20261030 --limit 15
.venv/Scripts/python.exe -m scripts.catalog_import validate --root outputs/catalog-demo-20261030
```

重跑沿用可讀、解碼與雜湊皆正確的圖片，不重複複製。圖片遺失／損壞時，若 manifest 有合法的本地原圖就修復；損壞檔會先保存於 cache/quarantine，再替換。沒有原圖時改為 missing／invalid，不把它提供給辨識。來源名稱、版本、代碼或圖片 URL 不一致時，將新舊資料寫入 `import_events.jsonl`，保留既有機體，不自動解決衝突。

目前是單一寫入程序工具；不要同時啟動兩個匯入程序或手動改寫同一份 Catalog。個別解析／圖片失敗可跳過並記錄；Catalog 結構錯誤或無法寫入錯誤紀錄時停止，不覆蓋既有 Catalog。失敗時可能留下未被引用的快取圖片，工具不自動刪除它們。

## Python 查詢

```python
from pathlib import Path
from gget_scanner.catalog import load_catalog
from gget_scanner.catalog.validator import validate_catalog

root = Path(".").resolve()
catalog = load_catalog(root / "data/catalog/units.json")
for issue in validate_catalog(catalog, root):
    print(issue.unit_id, issue.field, issue.message)

unit = catalog.get("7fdd93ad-f9bd-5b28-bd19-77632c66dcb1")
print(unit.name, unit.rarity)
paths = catalog.reference_paths(unit.unit_id, root, kind="artwork")
```

找不到機體時 `get()` 拋出 `KeyError`。`reference_paths()` 只考慮 downloaded 的圖片，重新解碼／比對雜湊；若檔案已壞則拋出 CatalogError，若沒有本地參考圖則回傳空 tuple。Loader 僅驗證結構，不宣稱圖片已實際存在，完整本地檢查需另呼叫 Validator。

## 隨機間隔與網路限制

Fetcher 元件預設等待 8～15 秒；手動 crawl 指令預設為 **6～9 秒**。已花在本地處理的時間會計入等待。重試也抽取新的間隔；目的是減少負載，不偽裝瀏覽器或規避存取限制。

使用 `GGETCatalogImporter/0.1` User-Agent；逾時 20 秒，暫時性網路錯誤與部分 5xx 最多重試 2 次。每個來源先檢查 robots.txt；規則不明、禁止、要求更慢間隔、重新導向、401／403／429 等情況停止。Fetcher 只接受明確啟用的 URL；crawl 依索引與已驗證頁面加入 URL，不猜測圖片位置。非空且全為註解的 robots.txt 沒有作用中的限制指令；空回應或 HTML 不視為有效規則。robots 檢查不代表再散布授權。

## 驗證範圍

- 15 台合成資料：同名不同 ID、EX、明示稀有度、各自的合成 WebP 圖片，匯入／增量／重跑／圖片路徑與內容對應。
- 不完整欄位、重複 ID／來源 ID、JSON 結構、中文路徑、無效圖片、圖片遺失與損壞、來源衝突、原子輸出失敗及 CLI 退出碼。
- HTTP 使用假回應與假時鐘，驗證隨機間隔、重試、robots 與存取拒絕；不向真實網站發送測試流量。
- 早期曾個別驗證 1,321 筆真實索引、27 筆公開詳情 HTML 與一張真實 WebP；後續完整抓取的本機紀錄顯示 1,321 台均成功，baseline 檢查再確認全部本地圖片的雜湊、尺寸與解碼。自動測試仍使用假回應驗證下載／續跑與停止行為，不把單次成功推論為來源未來改版後仍相容。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_catalog.py tests/test_catalog_import.py tests/test_catalog_http.py tests/test_catalog_crawl.py
```

沿用 OpenCV／NumPy／pytest，沒有新增套件。Context7 沒有完全對應已安裝 OpenCV 4.14 的文件，已查閱 4.13 官方文件，並以實際安裝版本測試 WebP 解碼與圖片錯誤處理；其他 Python／OpenCV 版本尚未實測。
