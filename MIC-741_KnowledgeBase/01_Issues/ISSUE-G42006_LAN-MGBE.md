# ISSUE G42006 — [LAN] Mgbe failed up connection automatically when 1st boot to desktop

| 欄位 | 內容 |
|------|------|
| Bug ID | **G42006** |
| PCB / Model | MIC-741 |
| 狀態 | Close |
| Final Solution Area | **BSP V1.0.3 retest pass** |
| 負責人 (Resolved by) | alex.hsu |
| Report | 2025-12-30 08:59:48 — kay.chuang — BSP V1.0.1 |
| Resolved | 2026-01-16 11:57:46 — alex.hsu |
| Close | 2026-01-16 12:00:32 — kay.chuang |
| 來源 | https://idesign.advantech.com/iDesignMVC3/IssueController/BugResolve?BugID=G42006 |

## 問題描述 (Symptom)
> Plug LAN cable (RJ45 + Fiber) and Mgbe failed connection when 1st boot to desktop after BSP flashed.

BSP 燒錄後第一次開機進桌面時，MGBE 網路介面無法自動 up / 建立連線。

## 解法 (Resolution — alex.hsu)
> Using `ip link up` after boot up to walk around race condition issue for 10g and nvrm drivers.

10G PHY driver 與 nvrm driver 之間存在開機 race condition，導致 MGBE 介面未能自動 up。
於 boot script 開機後以 `ip link set mgbeX_0 up` 強制拉起介面以繞過該 race condition。

## 對應 Commit
Repo: `mic_741_at7a1_jetpack_7.0`

| Commit | 日期 | Message | 說明 |
|--------|------|---------|------|
| `d867c08` | 2026-01-15 | Walk around nvpmodel issues for MGBE unlink. | **主要修改**：將 `ip link set mgbe0_0/1_0/2_0 up` 整進 `fix_nvpmodel`，並移除舊 `fix_network` 與 netplan yaml |
| `12339ac` | 2026-01-15 | BSP v1.0.3: Walk around nvpmodel issues for MGBE unlink. | 版號 bump → v1.0.3 (config.mk) |
| `0b4ad00` | 2026-01-16 | Unplug NVPModel fix. | 後續：於 `start()` 將 `fix_nvpmodel &` 註解掉 |

異動檔案（本 issue 相關）：
- `source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`
- `source/modify/driver/rootfs/etc/netplan/01-network-manager-all.yaml` (刪除)

## 修改前 code / diff
- 修改前：[`02_Original_Code/ISSUE-G42006_LAN-MGBE/main.sh.before`](../02_Original_Code/ISSUE-G42006_LAN-MGBE/main.sh.before)
- Diff（主要）：[`02_Original_Code/ISSUE-G42006_LAN-MGBE/fix_d867c08_main.sh.diff`](../02_Original_Code/ISSUE-G42006_LAN-MGBE/fix_d867c08_main.sh.diff)
- Diff（後續）：[`02_Original_Code/ISSUE-G42006_LAN-MGBE/fix_0b4ad00_main.sh.diff`](../02_Original_Code/ISSUE-G42006_LAN-MGBE/fix_0b4ad00_main.sh.diff)

## 後續關聯
- 此 issue 的 boot script 基礎來自 G42005（`80c608b` 新增的 `fix_nvpmodel`）。
- 同 repo 後續 `95cff04` (2026-05-21) "fix MGBE1 RST pin gpio definition conflict" 為 MGBE 相關硬體層後續修正，非本 issue。
