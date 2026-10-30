# 右上角 SP／NONE 概念驗證

目前只驗證 **SP／NONE**。使用者已確認尚未提供 SSP 範本，ULT 與星數亦不在本次實作範圍。這是獨立的實驗工具，尚未接進既有 `classify_card`／`gget-classify` 的正式輸出，不影響稀有度與職能判斷。

## 方法與檔案

- `src/gget_scanner/recognition/enhancement.py`：設定、參考載入與 `EnhancementClassifier`。
- `src/gget_scanner/pipeline/card_enhancement.py`：單張／批次 CLI 與可選 Debug。
- `data/profiles/card_enhancement.json`：尺寸、比例、ROI、尺度及拒答門檻。
- `tests/test_card_enhancement.py`：合成單元測試，涵蓋正例、缺資料、模糊結果、輸入異常、原圖保留、批次容錯與覆寫保護。

沿用現有標準化（200×400、相對比例誤差 5%）。在右上角搜尋區 `[140,0,200,65]`，對照標記過的真實參考卡區域 `[150,2,200,55]`。以 OpenCV `TM_SQDIFF_NORMED` 比較 BGR 色彩與空間排列，允許滑動與 0.95／1／1.05 尺度，距離越小越相似。沒有訓練模型、OCR 或新依賴。

各類選最佳參考匹配，再比較第一、二名差距。SP 距離上限 0.15，NONE 上限 0.10，類別差距至少 0.04，各類至少 2 個參考。**NONE 也需要已標記參考圖；沒有匹配到 SP 不會直接變成 NONE。** 缺參考、圖片不完整或分數不過門檻時回傳 UNKNOWN／AMBIGUOUS，保留最佳候選、其他候選、距離、尺度與位置。分數不是正確機率，`strict_filter_allowed` 固定 false。

完整區域保留了字形與背景，因此對背景變化敏感；這是本版刻意暴露、尚未解決的限制。不能保證遇到未支援的 SSP／ULT 會回傳 UNKNOWN；在沒有對應範本前，不應拿這個工具處理包含這些狀態的未知混合資料並視為可靠分類。

## 使用

目前本機參考包位於 `data/local_assets/recognition/enhancement-poc/references.json`，包含 3 張 SP 與 6 張 NONE 參考卡。圖片只留本機；新 clone 需自行準備。

```powershell
# 單張概念測試
.venv/Scripts/python.exe -m gget_scanner.pipeline.card_enhancement outputs/cards/initial/Test_SSR/card_002_r0_c2.png --config data/profiles/card_enhancement.json --references data/local_assets/recognition/enhancement-poc/references.json --output outputs/recognition/enhancement-single-01 --debug

# 批次；只處理 card_* 圖片
.venv/Scripts/python.exe -m gget_scanner.pipeline.card_enhancement outputs/cards/iPhone13pro/v2 --recursive --config data/profiles/card_enhancement.json --references data/local_assets/recognition/enhancement-poc/references.json --output outputs/recognition/enhancement-batch-01
```

輸出目錄必須全新且位於輸入目錄之外。`results.json` 記錄每張結果、支援／未支援類別、處理錯誤與耗時；Debug 另外輸出搜尋區及位置標示。單張損毀不影響其他圖片。退出碼 0 為完成（可有 UNKNOWN），1 為有圖片／比例錯誤，2 為設定或輸出失敗。

Python API：

```python
from gget_scanner.recognition.enhancement import (
    EnhancementClassifier, load_enhancement_config, load_enhancement_references,
)

config = load_enhancement_config("data/profiles/card_enhancement.json")
references = load_enhancement_references(
    "data/local_assets/recognition/enhancement-poc/references.json", config,
)
classifier = EnhancementClassifier(config, references)
normalization, enhancement = classifier.classify_card(card_image)
print(enhancement.to_dict())
```

參考 manifest 格式：

```json
{
  "schema_version": 1,
  "samples": [
    {"image": "cards/sample.png", "label": "SP", "group": "unique-artwork"}
  ]
}
```

路徑相對於 manifest，不能逃出其目錄。每張參考卡自動標準化並擷取 ROI，無需另訓練。加入 SSP 時可在設定 `classes` 加入 SSP 並提供至少兩張對應參考，再做獨立驗證；本版未附 SSP 樣本或驗證結果。避免重複同一張圖片湊參考數。

## 實際概念測試

以原先 424 張 iPad／iPhone v2 測資測試，逐張目視標籤來自已檢視的卡片總覽。排除參考卡面的所有重複 group、已知 ULT 與比例不符後，302 張可評估。各排除原因可能重疊；這批也含同一機體的不同裁切，因此不是獨立機體泛化準確率。

| 真值 | 接受且正確 | 接受但錯誤 | UNKNOWN／AMBIGUOUS |
| --- | ---: | ---: | ---: |
| SP（87 張） | 74 | 0 | 13 |
| NONE（215 張） | 33 | 0 | 182 |
| 合計（302 張） | 107 | 0 | 195 |

最佳候選（尚未套用拒答門檻）302／302 符合目視標籤；通過門檻的覆蓋率只有 **35.43%**。SP 覆蓋率 85.06%，NONE 15.35%。這證明目前樣本有候選排序訊號，**尚不代表完成可用的泛化分類器**。NONE 拒答多的主要原因是完整區域比對受立繪／背景差異影響，沒有為了提高通過數放寬門檻。

原 424 張有 40 張未通過比例檢查；本次仍沿用原設定，沒有強制拉伸。已知 ULT 卡片排除於準確率統計；SSP 沒有資料，不宣稱識別效果。

詳細結果與各資料夾的右上角搜尋區在本機 `outputs/recognition/enhancement-poc-20261031/`。參考卡／標記腳本在本機 archive，圖片、標籤與結果不提交 Git。

已執行新增 6 項單元測試，以及完整回歸 **238 passed、2 skipped**；略過的是缺少私有原始截圖的既有測試。另實際執行單張 Debug 與 iPhone v2 的 120 張批次 CLI；後者 8 張沿用既有比例錯誤，其他圖片成功處理。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_card_enhancement.py
.venv/Scripts/python.exe -m pytest
```
