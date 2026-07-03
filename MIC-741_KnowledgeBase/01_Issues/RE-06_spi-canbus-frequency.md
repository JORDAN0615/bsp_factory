# RE-06 — SPI-to-CAN (MCP2518FD) SPI clock too high

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `c8f55b4` |
| 日期 | 2026-02-09 |
| 類型 | FIX |
| 主要檔案 | `.../nv-platform/tegra264-p4071-0000.dtsi` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
SPI 介面的 MCP2518FD CAN 控制器在 `spi-max-frequency = 50MHz` 下不穩定/通訊錯誤（超出穩定工作範圍），需降頻。

## 解法（實際 commit 做法）
- 將兩個 SPI-CAN 節點的 `spi-max-frequency` 由 `50000000` 改為 `10000000`（MCP2518XFD SPI Max）。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-06_spi-canbus-frequency/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`c8f55b4.patch`。

## 🧪 LLM 試解任務
- 問題：SPI 介面的 MCP2518FD CAN 控制器在現行 SPI 時脈下通訊不穩，請調整 device tree 使其穩定。
- 評分重點：(1) 是否定位到兩個 SPI-CAN 節點的 `spi-max-frequency`；(2) 是否降到 MCP2518FD 合理值（~10MHz）。
