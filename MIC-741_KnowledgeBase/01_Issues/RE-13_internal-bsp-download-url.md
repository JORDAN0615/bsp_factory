# RE-13 — Point JP7.2 BSP download URLs to internal mirror

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `99d6b3e` |
| 日期 | 2026-06-17 |
| 類型 | CONFIG |
| 主要檔案 | `source/config/config.mk` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
BSP 下載 URL 指向 `developer.nvidia.com`（外網、慢/受限），需改為公司內部 mirror。

## 解法（實際 commit 做法）
- 將 driver/rootfs/source 下載 URL 改為內部鏡像 `172.17.22.195/tftp/NCG/mic/jp7.2`。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-13_internal-bsp-download-url/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`99d6b3e.patch`。

## 🧪 LLM 試解任務
- 問題：BSP 下載來源指向外網 NVIDIA，請改為公司內部 mirror。
- 評分重點：是否正確替換三個下載 URL 至內部伺服器。
