# RE-16 — I2C/CAN bus timeout: pinmux reset to rsvd on JP7.2

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `d0eeee7` |
| 日期 | 2026-06-22 |
| 類型 | FIX |
| 主要檔案 | `config.mk`、`.../bootloader/tegra264-mb1-bct-pinmux-p3834-xxxx-p4071-0000.dtsi` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推 — commit message 已詳述根因）
JP7.2 的 pinmux（xlsm Rev.9→Rev.14）把 I2C3/I2C9/CAN2/CAN3 腳位 reset 成 `rsvd1`，但 DT 中對應控制器仍 enabled，造成 bus timeout（例如 `i2cset bus 3` → `Write failed`）。

## 解法（實際 commit 做法）
- 於 MB1 BCT pinmux 將這些腳位還原為 JP7.1 的功能設定。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-16_fix-pinmux-i2c-can-rsvd/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`d0eeee7.patch`。

## 🧪 LLM 試解任務
- 問題：JP7.2 上 I2C3/I2C9/CAN2/CAN3 出現 bus timeout（i2cset Write failed），controller 有開但 pin 被設成 rsvd1，請修正 pinmux。
- 評分重點：(1) 是否定位到 pinmux 把這些 pin 設成 rsvd1 的根因；(2) 是否還原為正確功能（對照 JP7.1 / `after/`）。
