# RE-11 — MGBE1 RST pin GPIO definition conflict

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `aad8992` |
| 日期 | 2026-05-21 |
| 類型 | FIX |
| 主要檔案 | `.../bootloader/tegra264-mb1-bct-gpio-p3834-xxxx-p4071-0000.dtsi` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
MGBE1 的 reset 腳位 `TEGRA264_MAIN_GPIO(U,4)` 在 MB1 BCT gpio 清單中被重複/衝突定義，導致 MGBE1 reset 行為異常。

## 解法（實際 commit 做法）
- 於 gpio dtsi 清單移除衝突的 `TEGRA264_MAIN_GPIO(U, 4)`。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-11_fix-mgbe1-rst-gpio-conflict/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`aad8992.patch`。

## 🧪 LLM 試解任務
- 問題：MGBE1 RST 腳位 GPIO(U,4) 與其他定義衝突，請修正 MB1 BCT gpio 設定。
- 評分重點：是否定位並移除衝突的 GPIO(U,4) 定義。
