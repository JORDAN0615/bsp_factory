# RE-18 — Select SoM T5000/T4000 via bsp_som param

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `9fde196` |
| 日期 | 2026-06-24 |
| 類型 | FEATURE |
| 主要檔案 | `config.mk`、新增 `source/config/som/t4000.mk`、`t5000.mk`、`task_jenkins_build.sh`、`README.md` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
需支援同一 BSP 透過 `bsp_som` 參數切換 **T5000 / T4000** 兩種 SoM，避免硬編碼。

## 解法（實際 commit 做法）
- 新增 `som/t5000.mk`、`som/t4000.mk` 各自定義 SoM 專屬變數。
- `config.mk` 依 `bsp_som` 載入對應 `.mk`；更新 Jenkins build 腳本與 README。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-18_select-som-t5000-t4000/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`9fde196.patch`。

## 🧪 LLM 試解任務
- 問題：請讓 BSP 能以 `bsp_som` 參數在 T5000 / T4000 兩種 SoM 間切換（不要硬編碼）。
- 評分重點：(1) 參數化載入機制；(2) 兩個 SoM 設定檔的拆分；(3) build 腳本整合。
