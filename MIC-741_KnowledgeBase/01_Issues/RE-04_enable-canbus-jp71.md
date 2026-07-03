# RE-04 — Enable CAN bus (JetPack 7.1)

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `f1dbd21` |
| 日期 | 2026-02-05 |
| 類型 | FEATURE |
| 主要檔案 | 新增 `tegra264-p4071-0008+p3834-0008-nv.dts` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
JetPack 7.1 base 預設未啟用 CAN 控制器，需新增板級 device tree 以開啟 MIC-741 的 CAN bus。

## 解法（實際 commit 做法）
- 新增 `tegra264-p4071-0008+p3834-0008-nv.dts`，於其中開啟 CAN 相關節點。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-04_enable-canbus-jp71/`（含 before/ after/ 與 .patch）
- `before/`（無此檔，故 before 為空）、`after/`、`f1dbd21.patch`。

## 🧪 LLM 試解任務
- 問題：在 JP7.1 base 上啟用 MIC-741 的 CAN bus（device tree）。
- 評分重點：是否新增/啟用 CAN 控制器節點；與 `after/` 對照。
- 註：本 commit 為新增檔（before 無對應檔），LLM 任務偏向「依需求新增 DT」。
