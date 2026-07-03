# ISSUE G42005 — [GPU] GPU frequency mismatch spec under 120W power plan

| 欄位 | 內容 |
|------|------|
| Bug ID | **G42005** |
| Redmine ID | 141328 |
| PCB / Model | MIC-741 (Item 4742) |
| 狀態 | Close |
| Final Solution Area | **BSP V1.0.2 fixed** |
| 負責人 (Resolved by) | alex.hsu |
| Report | 2025-12-30 08:58:28 — kay.chuang — BSP V1.0.1 |
| Resolved | 2026-01-14 13:48:55 — alex.hsu |
| Close | 2026-01-14 13:51:38 — kay.chuang |
| 來源 | https://idesign.advantech.com/iDesignMVC3/IssueController/BugResolve?BugID=G42005 |

## 問題描述 (Symptom)
> Sometimes GPU frequcy mismatch spec under 120W power plan.
> Service of nvpmodel failed at same time.

120W power plan 下 GPU 頻率偶發不符規格；同時 `nvpmodel` service 啟動失敗。

## 解法 (Resolution — alex.hsu)
> Add restart nvpmodel service command in boot script.

在開機腳本 `bsp_init/main.sh` 中新增 `fix_nvpmodel`，於開機後 `systemctl restart nvpmodel`，確保 nvpmodel 套用正確的 power plan。

## 對應 Commit
Repo: `mic_741_at7a1_jetpack_7.0`

| Commit | 日期 | Message |
|--------|------|---------|
| `80c608b` | 2026-01-13 | BSP v1.0.2: Resolve 10G Aquantia PHY, power LED, SPI bus and nvpmodel issues. |

> 註：`80c608b` 為 BSP v1.0.2 的整合 commit，同時處理多個議題；本 issue 對應其中的 **nvpmodel boot script** 部分。

異動檔案（本 issue 相關）：
- `source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`

## 修改前 code / diff
- 修改前：[`02_Original_Code/ISSUE-G42005_GPU-nvpmodel/main.sh.before`](../02_Original_Code/ISSUE-G42005_GPU-nvpmodel/main.sh.before)
- Diff：[`02_Original_Code/ISSUE-G42005_GPU-nvpmodel/fix_80c608b_main.sh.diff`](../02_Original_Code/ISSUE-G42005_GPU-nvpmodel/fix_80c608b_main.sh.diff)

## 後續關聯
- 此 boot script 後續因 MGBE 議題在 G42006 被再次調整（`d867c08` / `0b4ad00`）。
