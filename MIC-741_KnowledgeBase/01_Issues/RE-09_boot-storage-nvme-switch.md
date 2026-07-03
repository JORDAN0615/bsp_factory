# RE-09 — boot_storage.sh: dynamic NVMe path switching

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `025c50c` |
| 日期 | 2026-03-24 |
| 類型 | FEATURE |
| 主要檔案 | `source/config/config.mk`、`source/config/task_patch.sh` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
燒錄流程的 `EXTERNAL_DEVICE`（NVMe 路徑）寫死，無法依實機 NVMe 位置動態切換；需提供安全、可手動操作的設定方式。

## 解法（實際 commit 做法，取自 commit message）
- 實作 `jetpack_7.0_create_adv_boot_storage_v2` 產生 helper script。
- 支援動態修改 `jetson-agx-thor-devkit.conf` 的 `EXTERNAL_DEVICE`。
- 使用 `sed --follow-symlinks` 保持設定連結完整性。
- 將參數設定與 flash 流程解耦，改為較安全的手動流程。
- 於 `task_patch.sh` 註冊新函式呼叫。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-09_boot-storage-nvme-switch/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`025c50c.patch`。

## 🧪 LLM 試解任務
- 問題：燒錄的 NVMe 路徑 (`EXTERNAL_DEVICE`) 寫死，請改為可動態切換、且與 flash 流程解耦的安全做法。
- 評分重點：(1) 動態改 `EXTERNAL_DEVICE`；(2) `sed --follow-symlinks` 等符號連結保護；(3) 解耦設計。
