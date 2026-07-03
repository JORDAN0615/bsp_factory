# RE-03 — Remove EA (early-access) GPU display driver

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `c158015` |
| 日期 | 2026-02-05 |
| 類型 | CHANGE |
| 主要檔案 | `source/config/task_after_kernel.sh`、刪除 `opensource-gpu-disp-ea/*.ko` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
rootfs 內夾帶 early-access 版 NVIDIA GPU 顯示 driver（`nvidia-drm/modeset/uvm/nvidia.ko`），需移除以改用正式版，避免顯示驅動衝突。

## 解法（實際 commit 做法）
- 刪除 `.../updates/opensource-gpu-disp-ea/` 下四個 `.ko`。
- 調整 `task_after_kernel.sh` 不再安裝 EA driver。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-03_remove-ea-graphic-driver/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`c158015.patch`。

## 🧪 LLM 試解任務
- 問題：rootfs 夾帶 EA 版 GPU 顯示 driver 造成衝突，請移除並調整 kernel 後處理腳本。
- 評分重點：是否正確移除 EA `.ko` 並改 `task_after_kernel.sh`。
