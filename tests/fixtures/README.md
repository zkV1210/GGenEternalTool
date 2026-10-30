# 測試資料

公開測試由 `tests/conftest.py` 直接產生合成圖片，使用不同顏色及不對稱角落標記驗證卡片內容、順序與透視方向，不需要遊戲素材或二進位 fixture。

本機遊戲截圖放在 `private/`，整個目錄均受根目錄 `.gitignore` 忽略，包含圖片、私人設定及任何衍生資料。原始 `Test.png` 已移至 `private/Test.png`，移動前後 SHA-256 相同：

```text
AEE5F89B0B8010FB837FA3C5C933508A68EDFF4FDB355974066FCE5867582A65
```

`data/profiles/test_screenshot.json` 是這張 2388×1668 圖片的手動 Layout，只有座標，沒有圖片內容。更換截圖、比例或遊戲 UI 後需要重新校準，不能把這份設定當成通用遊戲版面。

`tests/test_private_screenshot.py` 在圖片存在時額外檢查兩種裁切模式；不存在時略過，所有合成測試仍可執行。測試本身不寫入卡片產物。需要目視驗證時請執行 README 的 CLI，輸出到已忽略的 `outputs/`，並使用新的子目錄，避免覆寫既有結果。

不要將 `private/` 圖片或衍生裁切加入 Git。若未來新增可公開的外部 fixture，需先確認來源與授權。
