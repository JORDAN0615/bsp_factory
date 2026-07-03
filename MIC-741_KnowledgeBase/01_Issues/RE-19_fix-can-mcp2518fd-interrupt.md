# RE-19 — CAN dead on JP7.2: MCP2518FD interrupt + on-demand enable

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `071c674` |
| 日期 | 2026-06-26 |
| 類型 | FIX（root cause 已詳述） |
| 主要檔案 | `.../bootloader/tegra264-mb1-bct-pinmux-p3834-xxxx-p4071-0000.dtsi`、新增 `rootfs/etc/skel/can_enable.sh`、`docs/can-bus-pinmux-interrupt.md` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推 — commit message 已詳述根因）
CAN（can0/can1）在 JP7.2 完全無作用。兩個根因：
1. **pinmux**：JP7.2 重新產生的 MB1 BCT 把 CAN INT 腳（`soc_gpio21_pdd3` / `soc_gpio22_pdd4`）的 `nvidia,enable-input` 由 ENABLE(7.1) 翻成 DISABLE，SoC 感測不到訊號線，IRQ 永不觸發。
2. **INT 線被拉 LOW**（非真正 idle-high）：level-low IRQ 風暴 → 被 spurious-disabled，R39 kernel 上自啟動也不穩。

## 解法（實際 commit 做法）
- pinmux 還原 CAN INT 腳 `enable-input` 為 ENABLE（需 reflash bootloader/BCT）。
- 新增 `can_enable.sh`（經 rootfs `/etc/skel` 佈署到 `/home/mic-741`）持續推 GPIO interrupt-enable bit 直到 genirq 進入 poll 模式。
- 為 AD 安全考量，CAN 預設關閉，需手動 `sudo ~/can_enable.sh` 啟用。
- 文件：`docs/can-bus-pinmux-interrupt.md`。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-19_fix-can-mcp2518fd-interrupt/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`071c674.patch`。

## 🧪 LLM 試解任務
- 問題：JP7.2 上 CAN can0/can1 完全無作用（IRQ 不觸發）。請從 pinmux 與中斷處理兩方面修復，並提供安全的按需啟用方式。
- 評分重點：(1) 是否定位到 pinmux `enable-input` 被設成 DISABLE 的根因；(2) 是否處理 level-low IRQ 被 spurious-disable 的問題（poll/nudge）；(3) 是否考量 AD 安全（預設關閉、手動啟用）。
