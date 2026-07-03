# RE-10 — Build uses wrong SoM (config.mk bsp_som)

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `ea6e486` |
| 日期 | 2026-03-25 |
| 類型 | FIX / build |
| 主要檔案 | `source/config/config.mk` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
`config.mk` 的 `bsp_som` 設為 `Thor`，導致 build 取到錯誤的 SoM 檔名；應指向實際使用的 SoM。

## 解法（實際 commit 做法）
- `bsp_som=Thor` → `bsp_som=T5000`。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-10_fix-som-filename/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`ea6e486.patch`。

## 🧪 LLM 試解任務
- 問題：build 取到錯誤的 SoM 檔名，請修正 `config.mk` 的 SoM 設定。
- 評分重點：是否將 `bsp_som` 改為正確的 SoM（T5000）。
