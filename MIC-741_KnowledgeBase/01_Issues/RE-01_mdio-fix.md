# RE-01 — MDIO / Ethernet PHY bring-up (MDIO fix)

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `04b78ab` |
| 日期 | 2025-12-24 |
| 類型 | FIX / bring-up |
| 主要檔案 | bootloader gpio/pinmux dtsi、`tegra264-p4071-0000.dtsi`、kernel `defconfig`、新增 `igb_main.c`、`aquantia_firmware.c` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
MIC-741 板上乙太網路 PHY 的 MDIO 管理介面無法正常運作（PHY 無法被偵測/設定），需修正 MDIO 相關 pinmux / device tree 與 PHY driver（Intel igb、Aquantia firmware）以讓網路 PHY 正常 bring-up。

## 解法（實際 commit 做法）
- 調整 bootloader MB1 BCT 的 gpio / pinmux dtsi 與 `tegra264-p4071-0000.dtsi` 的 MDIO 相關設定。
- 開啟 kernel defconfig 對應選項。
- 導入 `igb_main.c`、`aquantia_firmware.c` driver。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-01_mdio-fix/`（含 before/ after/ 與 .patch）
- `before/` 修改前完整檔案集，`after/` 修改後，`04b78ab.patch` 為完整 diff。

## 🧪 LLM 試解任務
- 平台：MIC-741 (AT7A1)、NVIDIA Jetson、JetPack 7.0。
- 輸入：`before/` 全部檔案 + 下方問題（請勿看 `after/`）。
- 問題：乙太網路 PHY 的 MDIO 介面無法運作，請修正 device tree / pinmux 並補上必要的 PHY driver 設定。
- 評分重點：(1) 是否定位到 MDIO pinmux / DT 節點；(2) 是否處理 PHY driver（igb / aquantia）；(3) 與 `after/` 對照。
