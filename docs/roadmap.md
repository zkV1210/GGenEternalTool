# 後續開發方向

目前已完成單張圖片的 Layout 載入、解析、裁切、Debug Overlay 與 CLI，以及獨立的本地 Catalog 與卡片屬性辨識 MVP。Catalog 的範圍見 [catalog.md](catalog.md)，SR／SSR／UR 粗框線比對與三種職能徽章辨識見 [recognition.md](recognition.md)。現有幾何規則見 [architecture.md](architecture.md)；其餘下列功能仍為規劃。

## GUI 校準與 Layout 產生

預計讓玩家上傳最終截圖，依序框選第一張卡片的 TL／TR／BR／BL、標記第二張卡片及下一排卡片的位置，再設定欄數與排數。由這些標記計算水平、垂直位移向量，預覽完整網格，微調後輸出同一份 Layout Schema。

GUI 負責將像素標記轉成 0～10000 的整數座標，也需顯示取整後的預覽；不在 Cropper 加入 GUI 或手機型號規則。更後期的自動 UI 偵測亦只產生 Layout，沿用同一套 Loader／Resolver 驗證。獨立卡片覆寫與卡片內部 Artwork、Name、Rarity、Progression ROI 留待實際需求出現後擴充 Schema。

## 辨識、遊戲資料庫與 Inventory

- `recognition`：已實作裁切卡片標準化、三段粗框線 Lab 參考比對、職能徽章顏色／遮罩模板驗證、單張／批次工具與 Debug；回傳候選、原始分數與拒答原因，嚴格篩選預設關閉。N／R 真實樣本、機體立繪匹配、OCR 與其他狀態辨識仍待擴充。
- `catalog`：已建立識別資料模型、JSON Loader／Validator、離線匯入及可續跑的公開清單／圖片抓取 CLI。已有一次 1,321 筆固定清單完成的本機快照，baseline 檢查通過所有參考圖片的解碼、雜湊與尺寸驗證；與玩家持有狀態分開，不包含性能資料庫，也不宣稱涵蓋遊戲全機體。
- `inventory`：讓 Quick Scan 與 Detailed Scan 共用帳號資料結構，區分已辨識、玩家確認及未知值；未知不視為 0 或滿等。
- `export`：在 Inventory 格式確定後處理帳號 JSON 及未來 CSV；目前 CLI 的裁切 manifest 不取代 Inventory。
- `app`：未來可能使用 Streamlit 提供操作介面，目前不增加 UI 依賴。

尚未實作的責任不建立 Python 空殼模組。屬性辨識使用獨立設定，不修改 Layout Schema 或既有 Cropper。

## Capture／Tracking 與完整性

未來 `capture` 負責 ADB／模擬器擷取、捲動與畫面穩定檢查；Tracking Pipeline 持有跨畫面狀態。可能逐次讀取前兩排，再捲動取得新卡片，但不能只依賴右側捲動條推算掃描完成度。

應結合：

1. 捲動條位置，估計列表相對進度。
2. 相鄰截圖重複卡片，確認畫面連續性。
3. 卡片順序與重疊區域，檢查跳頁或漏掃。
4. 跨畫面去重；實際辨識鍵與同機體多份持有的處理方式待確認。
5. 無法確認連續性時，標記需要重新掃描，不假定完整。

載入、翻頁失敗、停止與恢復也屬此層責任。Layout Resolver 與 Cropper 維持 Stateless，只處理單張圖片及本次明確提供的設定，不承擔完整性保證。

## LLM 與攻略知識

後續可建立保留來源、日期與授權資訊的攻略知識庫，再提供 Skills／MCP 或其他工具介面供 LLM 查詢。精確計算與合法性驗證交由程式處理；修改玩家 Inventory 前需提出變更並取得確認。

上述 LLM 整合尚未實作，不加入 API Key 或外部服務。
