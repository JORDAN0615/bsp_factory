# RE-14 — Customize AT7A1 board for JetPack 7.2

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `eaf02e9` |
| 日期 | 2026-06-17 |
| 類型 | FEATURE / board bring-up（大型） |
| 主要檔案 | bpmp/pinmux/gpio dts、`tegra264-p4071-0000.dtsi`/`tegra264.dtsi`、`defconfig`、`spi-tegra114.c`、`aquantia_main.c`、conftest、`nv-oobe.sh`、dpkg status |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
在 JP7.2 (L4T r39.2.0) base 上套用 MIC-741 **AT7A1** 板的完整客製。

## 解法（實際 commit 做法，取自 commit message）
- **Device tree / bootloader**：bpmp 開 pcie@3、調 clock/system-cfg；pinmux & gpio BCT 套 AT7A1 腳位；tegra264/p4071 DT 的 SPI、PCIe、power LED、gpio-mode。
- **Kernel**：defconfig SPI 選項；`spi-tegra114` downstream driver（tap-delay/high-speed）；aquantia PHY 調整；conftest 強化編譯器版本解析；移除 pinctrl-tegra debug override（回 stock）。
- **Rootfs**：`nv-oobe.sh` 首次開機跳過 OOBE 並 resize rootfs 至滿碟；dpkg status hold 住 nvidia-l4t-kernel 等套件。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-14_customize-at7a1-jp72/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`eaf02e9.patch`。

## 🧪 LLM 試解任務
- 問題：在 JP7.2 base 上完成 MIC-741 AT7A1 板客製（DT/kernel/rootfs）。
- 評分重點：此為大型整合任務，著重方向涵蓋度（SPI/PCIe/power LED/OOBE/套件 hold）與 `after/` 對照。
