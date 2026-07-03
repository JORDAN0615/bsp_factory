# RE-07 — Genericize Camera SIPL download + support v38.4.0

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `4e2f1bc` |
| 日期 | 2026-03-09 |
| 類型 | REFACTOR |
| 主要檔案 | `source/config/task_download_after.sh` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
Camera SIPL 下載流程寫死特定版本，難以維護；需重構為可參數化的通用下載並支援 v38.4.0。

## 解法（實際 commit 做法）
- 重構 `task_download_after.sh`，將 Camera SIPL 下載參數化並新增 v38.4.0 支援。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-07_camera-sipl-genericize/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`4e2f1bc.patch`。

## 🧪 LLM 試解任務
- 問題：Camera SIPL 下載流程版本寫死，請重構為通用化並支援新版本 v38.4.0。
- 評分重點：是否參數化版本、保留相容性；與 `after/` 對照。
