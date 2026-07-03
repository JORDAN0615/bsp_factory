# RE-08 — Revert mttcan errors + update MGBE3 shutdown config

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `44338db` |
| 日期 | 2026-03-09 |
| 類型 | FIX |
| 主要檔案 | `config.mk`、`tegra264-p4071-0000.dtsi`、`tegra264-p4071-0000+p3834-0008-nv.dts`（rename） |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
先前對 mttcan 的改動造成 build/runtime 錯誤，需回退；同時 MGBE3 介面的 shutdown 設定需更新。並把板級 dts 由 `p4071-0008+...` 命名修正回 `p4071-0000+...`。

## 解法（實際 commit 做法）
- 回退造成錯誤的 mttcan 改動。
- 更新 `tegra264-p4071-0000.dtsi` 的 MGBE3 shutdown 設定。
- 重新命名/對齊板級 dts 檔名與 `config.mk`。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-08_revert-mttcan-mgbe3-shutdown/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`44338db.patch`。

## 🧪 LLM 試解任務
- 問題：mttcan 的改動造成錯誤需回退，且 MGBE3 shutdown 設定需修正，請處理。
- 評分重點：(1) 是否回退 mttcan；(2) MGBE3 shutdown DT；(3) dts 命名對齊。
