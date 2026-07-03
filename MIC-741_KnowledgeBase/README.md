# MIC-741 知識庫 (Knowledge Base)

建立日期：2026-06-29
擁有者：alex.hsu

## 目的
彙整 MIC-741 平台的 bug 單、對應 commit、解 issue 前的原始 code，以及歷史 git 紀錄，做為知識庫。

## 資料夾結構
```
MIC-741_KnowledgeBase/
├── README.md              <- 本說明檔
├── 01_Issues/             <- 每張 issue 一個 .md：bug 單內容 + 對應 commit message
├── 02_Original_Code/      <- 每個 issue 一個子資料夾，存「修改前」的原始 code
├── 03_Git_History/        <- mic_741_jetpack_7.2 過去 git history 的整理
└── _raw/                  <- 原始匯出資料（bug 清單 CSV/HTML、git log 原始輸出）
```

## 資料來源
| 編號 | 來源 | URL | 用途 |
|------|------|-----|------|
| 1 | DQA / i-Design Bug 系統 | https://idesign.advantech.com/iDesignMVC3/IssueController/Bugs (filter: PCB MIC-741) | 搜尋 alex.hsu 的 bug 單 |
| 2 | GitLab BSP repo | https://172.17.4.45/isystem-esg-linux-bsp/mic_741_at7a1_jetpack_7.0 | 取對應 commit message / 修改前 code |
| 3 | GitLab BSP repo | https://172.17.4.45/isystem-esg-linux-bsp/mic_741_jetpack_7.2 | 過去 git history 整理 |

## 狀態（2026-06-29 完成）
- [x] 建立資料夾結構
- [x] 取得 DQA bug 單（alex.hsu 提供 2 張 MHTML：G42005、G42006）
- [x] clone 兩個 repo，比對 commit
- [x] 整理 issue 單（01_Issues）
- [x] 保存修改前 code + diff（02_Original_Code）
- [x] 整理 7.2 git history（03_Git_History）

## 索引
### 01_Issues
DQA 實際 bug 單（`ISSUE-` 前綴）+ 由 git history 反推的 issue（`RE-` 前綴，索引見 [RE-INDEX.md](01_Issues/RE-INDEX.md)）。
| Issue | 標題 | 對應 commit | 狀態 |
|-------|------|-------------|------|
| [G42005](01_Issues/ISSUE-G42005_GPU-nvpmodel.md) | [GPU] GPU frequency mismatch under 120W power plan | `80c608b` | Close (BSP v1.0.2) |
| [G42006](01_Issues/ISSUE-G42006_LAN-MGBE.md) | [LAN] Mgbe failed up connection on 1st boot | `d867c08` / `0b4ad00` | Close (BSP v1.0.3) |
| [RE-01 ~ RE-19](01_Issues/RE-INDEX.md) | 由 git history 反推的 19 張 issue（MDIO/CAN/pinmux/PCIe/SoM…） | 各 commit | 反推 |

### 02_Original_Code （LLM 試改 + 對比用）
每個 issue 一個資料夾，含 `before/`（修改前完整檔）、`after/`（修正後完整檔）、diff。流程見 [02_Original_Code/README.md](02_Original_Code/README.md)。
- `ISSUE-G42005_*` / `ISSUE-G42006_*` — DQA 實際 bug 單（含 PROMPT.md）
- `RE-01_* ~ RE-19_*` — 由 git history 反推的 19 個 issue（含 .patch；issue 單在 `01_Issues/RE-*.md`）

### 03_Git_History （含完整修改紀錄）
- [mic_741_jetpack_7.2_history.md](03_Git_History/mic_741_jetpack_7.2_history.md) — 389 commits，分三階段（7.0 base → 7.1 → 7.2 bring-up）
- [patches/](03_Git_History/patches/) — 32 個專案 commit 的**全量 diff**（每 commit 一個 .patch），索引見 [patches/INDEX.md](03_Git_History/patches/INDEX.md)，供本地 LLM 理解。
> 由這些 commit 反推的 issue 已併入 `01_Issues`（`RE-` 前綴）與 `02_Original_Code`（`RE-` 前綴）。

## 備註
- clone 的 repo 放在上層 `..\_repos\`（工作用，非知識庫成品）。
- 兩個 repo 早期 history 共用；G42005/G42006 的修正同時存在於兩 repo。
- 關鍵檔案：`source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`（開機腳本）。
