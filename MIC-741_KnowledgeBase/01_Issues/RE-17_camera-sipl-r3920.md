# RE-17 — Switch Camera SIPL to L4T r39.2.0 (JetPack 7.2)

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `70ebb17` |
| 日期 | 2026-06-23 |
| 類型 | CONFIG |
| 主要檔案 | `source/config/task_download_after.sh` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
搭配 JP7.2 base，Camera SIPL 套件需切換到對應的 L4T r39.2.0 版本。

## 解法（實際 commit 做法）
- 於 `task_download_after.sh` 將 Camera SIPL 下載切到 L4T r39.2.0。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-17_camera-sipl-r3920/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`70ebb17.patch`。

## 🧪 LLM 試解任務
- 問題：JP7.2 base 需搭配對應版本的 Camera SIPL，請更新下載設定到 r39.2.0。
- 評分重點：是否正確切換 SIPL 版本（對照 `after/`）。
