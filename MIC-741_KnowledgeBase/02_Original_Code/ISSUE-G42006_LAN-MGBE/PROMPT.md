# LLM 試改任務 — ISSUE G42006

## 平台
Advantech MIC-741 (AT7A1)，NVIDIA Jetson，JetPack 7.0 / L4T，BSP v1.0.2（已含 G42005 的 nvpmodel 修正）。

## 原始碼脈絡
`before/` 內為本 issue 修正範圍（commit `d867c08` → `12339ac` → `0b4ad00`）觸及的**完整檔案集**（保留原始 `source/...` 路徑，共 5 檔）。

**主要待修檔案**：
- `before/source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`（BSP 開機初始化腳本）
- `before/source/modify/driver/rootfs/etc/netplan/01-network-manager-all.yaml`（netplan 設定）

## 問題 (Bug)
> Plug LAN cable (RJ45 + Fiber) and Mgbe failed connection when 1st boot to desktop after BSP flashed.

BSP 燒錄後第一次開機進桌面時，MGBE 網路介面無法自動 up / 建立連線。
根因：10G PHY driver 與 nvrm driver 在開機階段有 race condition，介面尚未就緒。

## 任務
請只根據 `before/` 的檔案，修改開機流程以解決 MGBE 第一次開機無法連線的問題。
請輸出修改後的完整 `main.sh`（若你認為需調整/移除 netplan 設定也請說明）。

## 評分 / 對比
- 人工正解：`after/source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`（注意：人工版**移除**了 `01-network-manager-all.yaml`，故 after/ 無此檔）
- 對應 diff：`fix_d867c08_main.sh.diff`（主要）、`fix_0b4ad00_main.sh.diff`（後續）
- 人工解法重點：移除舊 `fix_network`／netplan 那套；開機後在 `fix_nvpmodel` 內以 `ip link set mgbe0_0/mgbe1_0/mgbe2_0 up` 強制拉起介面繞過 race condition；後續 `0b4ad00` 再把 `fix_nvpmodel &` 註解掉。
- 對比時可檢查 LLM 是否：(1) 認出 race condition 本質；(2) 採用開機後強制 `ip link up`；(3) 涵蓋全部 MGBE 介面（含 SFP 的 mgbe2_0）。
