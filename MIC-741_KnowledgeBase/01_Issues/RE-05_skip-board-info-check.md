# RE-05 — Flash fails: skip board EEPROM/info check

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `e9b4042` |
| 日期 | 2026-02-05 |
| 類型 | FIX / flash |
| 主要檔案 | `source/modify/driver/p3834-0008-p4071-0000-nvme.conf` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
MIC-741 載板無 board ID EEPROM，燒錄流程在「board information / EEPROM 檢查」階段失敗，導致無法 flash。

## 解法（實際 commit 做法）
- 於 `*-nvme.conf` 加入 `SKIP_EEPROM_CHECK=1` 跳過 EEPROM 檢查。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-05_skip-board-info-check/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`e9b4042.patch`。

## 🧪 LLM 試解任務
- 問題：載板無 EEPROM，燒錄時 board information 檢查失敗，請修改 flash 設定使其略過該檢查。
- 評分重點：是否在 nvme.conf 正確加入 `SKIP_EEPROM_CHECK=1`。
