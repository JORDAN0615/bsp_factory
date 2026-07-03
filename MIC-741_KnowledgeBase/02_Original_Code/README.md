# 02_Original_Code — 原始 Code 與人工修正對比集

用途：提供每個 issue「修改前的完整原始 code」，讓本地端 LLM 先嘗試自行修改，再與「人工修改後的新 code」對比，評估 LLM 解題能力。

## 每個 issue 資料夾結構
```
ISSUE-<BugID>_<slug>/
├── before/        ← 修正 commit 觸及的「完整檔案集」修改前版本，保留原始 source/... 路徑
│                     （bug 仍存在；提供完整原始碼脈絡給 LLM）
├── after/         ← 同一批檔案人工修改後的完整版本（參考正解）
├── PROMPT.md      ← 給 LLM 的任務描述（問題 + 主要待修檔 + 對比重點）
└── *.diff         ← 人工修正的 git diff（before → after）
```
> `before/`、`after/` 為**完整檔案集**（含該 commit 同時改到的其他檔，如 dtsi/driver/config），
> 讓 LLM 面對完整脈絡而非單檔片段。實際要改的「主要檔案」在 PROMPT.md 標明。
> 新增(A)的檔只在 after、刪除(D)的檔只在 before，故兩側檔數可能不同。

## 建議流程
1. 把 `PROMPT.md` + `before/` 內檔案餵給本地 LLM。
2. 收集 LLM 產出的修改版。
3. 與 `after/` 對比（或對照 `*.diff`），用 PROMPT.md 的「對比重點」評分。

## 兩類資料夾
- **`ISSUE-*`**（DQA 實際 bug 單）：含 `before/`、`after/`、`PROMPT.md`、`*.diff`。
- **`RE-*`**（由 git history 反推，共 19 個）：含 `before/`、`after/`、`<hash>.patch`；對應 issue 單與 LLM 試解任務在 [`../01_Issues/RE-*.md`](../01_Issues/RE-INDEX.md)。

## DQA bug 單清單
| Issue | 待修檔 | before→after 重點 |
|-------|--------|-------------------|
| ISSUE-G42005_GPU-nvpmodel | main.sh | 新增 `fix_nvpmodel`（restart nvpmodel service） |
| ISSUE-G42006_LAN-MGBE | main.sh、01-network-manager-all.yaml | 改用 `ip link up` 繞過 10g/nvrm race；移除 netplan yaml |

> RE 系列清單見 [`../01_Issues/RE-INDEX.md`](../01_Issues/RE-INDEX.md)。詳細 issue 背景見 [`../01_Issues/`](../01_Issues/)。
