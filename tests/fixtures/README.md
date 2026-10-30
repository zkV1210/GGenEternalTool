# 測試資料

公開測試由 `tests/conftest.py` 直接產生合成圖片，使用不同顏色及不對稱角落標記驗證卡片內容、順序與透視方向，不需要遊戲素材或二進位 fixture。

本機遊戲截圖放在 `private/`，整個目錄均受根目錄 `.gitignore` 忽略，包含圖片、私人設定及任何衍生資料。原始 `Test.png` 現為 `private/Test_UR.png`，SHA-256 相同：

```text
AEE5F89B0B8010FB837FA3C5C933508A68EDFF4FDB355974066FCE5867582A65
```

`data/profiles/test_screenshot.json` 是這張 2388×1668 圖片的手動 Layout，只有座標，沒有圖片內容。更換截圖、比例或遊戲 UI 後需要重新校準，不能把這份設定當成通用遊戲版面。

`tests/test_private_screenshot.py` 在圖片存在時額外檢查兩種裁切模式；不存在時略過，所有合成測試仍可執行。測試本身不寫入卡片產物。需要目視驗證時請執行 README 的 CLI，輸出到已忽略的 `outputs/`，並使用新的子目錄，避免覆寫既有結果。

不要將 `private/` 圖片或衍生裁切加入 Git。若未來新增可公開的外部 fixture，需先確認來源與授權。

`test_auto_scan.py` 使用原始 2388×1668 `Test_UR.png`（相容舊檔名 `Test.png`）與目視檢查的結構外框比較 IoU，並檢查 0.65／1.3 倍縮放與 JPEG 品質 70。換成其他尺寸時會略過這組固定標註；標註只作測試預期，不作演算法輸入。原圖及縮放圖取得 16 張，JPEG 允許保守拒絕 1 張。這些衍生圖不是其他裝置的原始截圖；1536×710、3120×1440、1536×1073 素材尚缺。

九張原始私有測資皆為 2388×1668：`Test_SR`、`Test_SSR`、`Test_UR` 各有無後綴、`_touch_top`、`_cut_top` 三種 PNG。`test_nine_private_screenshots_match_annotated_rows` 驗證每張各 16 個框、正確來源列欄及每個框 IoU 大於 0.90；`cut_top` 預期跳過初始列，輸出第 1、2 列。個別檔案缺少時只略過相應案例。

本次本機檢查輸出在 `outputs/<測資檔名>/`，每個目錄含 Overlay、16 張卡片、Layout、manifest，另有檢查用的 `cards_overview.png`；彙整為 `outputs/nine_results.md`。144 張裁切皆與來源像素及重新載入 Layout 比對，並目視檢查九張卡片總覽。輸出與測資仍受忽略規則保護，不加入 Git。
