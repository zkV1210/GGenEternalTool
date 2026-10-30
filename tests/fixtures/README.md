# 測試資料

公開測試由 `tests/conftest.py` 直接產生合成圖片，使用不同顏色及不對稱角落標記驗證卡片內容、順序與透視方向，不需要遊戲素材或二進位 fixture。

本機遊戲截圖放在 `private/<裝置名稱>/`，目前有 `IPad/` 與 `iPhone13pro/`，各九張 PNG。整個 `private/` 均受根目錄 `.gitignore` 忽略，包含所有裝置子目錄與衍生資料。原始 `Test.png` 現為 `private/IPad/Test_UR.png`，SHA-256 相同：

```text
AEE5F89B0B8010FB837FA3C5C933508A68EDFF4FDB355974066FCE5867582A65
```

`data/profiles/test_screenshot.json` 是這張 2388×1668 圖片的手動 Layout，只有座標，沒有圖片內容。更換截圖、比例或遊戲 UI 後需要重新校準，不能把這份設定當成通用遊戲版面。

`tests/test_private_screenshot.py` 在圖片存在時額外檢查兩種裁切模式；不存在時略過，所有合成測試仍可執行。測試本身不寫入卡片產物。需要目視驗證時請執行 README 的 CLI，輸出到已忽略的 `outputs/`，並使用新的子目錄，避免覆寫既有結果。

不要將 `private/` 圖片或衍生裁切加入 Git。若未來新增可公開的外部 fixture，需先確認來源與授權。

`test_auto_scan.py` 使用原始 2388×1668 `Test_UR.png`（相容舊檔名 `Test.png`）與目視檢查的結構外框比較 IoU，並檢查 0.65／1.3 倍縮放與 JPEG 品質 70。換成其他尺寸時會略過這組固定標註；標註只作測試預期，不作演算法輸入。原圖及縮放圖取得 16 張，JPEG 允許保守拒絕 1 張。這些衍生圖不是其他裝置的原始截圖；1536×710、3120×1440、1536×1073 素材尚缺。

九張原始私有測資皆為 2388×1668：`Test_SR`、`Test_SSR`、`Test_UR` 各有無後綴、`_touch_top`、`_cut_top` 三種 PNG。`test_nine_private_screenshots_match_annotated_rows` 驗證每張各 16 個框、正確來源列欄及每個框 IoU 大於 0.90；`cut_top` 預期跳過初始列，輸出第 1、2 列。個別檔案缺少時只略過相應案例。

以 `python -m scripts.layout_batch` 重跑兩個算法、兩個裝置的 36 個案例，輸出按 `outputs/<裝置名稱>/<算法版本>/<測資名稱>/` 分類。原有平面輸出已清除。成功案例含卡片、Overlay、Layout、manifest 與卡片總覽；失敗保留 run.json／run.log。總入口為 `outputs/README.md`。批次測試確認輸出像素與重載 Layout 一致；框選是否正確仍需獨立人工驗證，尤其 iPhone 裁切列存在誤判。測資與輸出均不加入 Git。
