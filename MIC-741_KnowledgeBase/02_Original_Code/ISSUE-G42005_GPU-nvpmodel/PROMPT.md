# LLM 試改任務 — ISSUE G42005

## 平台
Advantech MIC-741 (AT7A1)，NVIDIA Jetson，JetPack 7.0 / L4T，BSP v1.0.1。

## 原始碼脈絡
`before/` 內為修正 commit `80c608b` 觸及的**完整檔案集**（保留原始 `source/...` 路徑，共 9 檔，含 config、bootloader dtsi、kernel driver 等），讓你掌握完整脈絡。

**主要待修檔案**（本 issue 真正要改的）：
`before/source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`
（開機時由 systemd 觸發的 BSP 初始化腳本）

> 註：`80c608b` 是多議題整合 commit，同時處理 10G PHY / power LED / SPI 等；本 issue 僅需處理 nvpmodel / GPU power plan 部分。

## 問題 (Bug)
> Sometimes GPU frequcy mismatch spec under 120W power plan.
> Service of nvpmodel failed at same time.

在 120W power plan 下，GPU 頻率偶發不符合規格；同時 `nvpmodel` service 啟動失敗，導致 power plan 未正確套用。

## 任務
請根據 `before/` 的原始碼脈絡，修改開機腳本 `main.sh` 以解決上述問題。
請輸出修改後的完整 `main.sh`。

## 評分 / 對比
- 人工正解：`after/source/modify/driver/rootfs/opt/advantech/service/bsp_init/main.sh`（`after/` 為同 commit 修改後完整檔案集）
- 對應 diff：`fix_80c608b_main.sh.diff`
- 人工解法重點：新增 `fix_nvpmodel` 函式，於開機後 `sleep` 再 `systemctl restart nvpmodel`，並在 `start()` 以背景方式呼叫。
- 對比時可檢查 LLM 是否：(1) 想到 restart nvpmodel service；(2) 處理啟動時序（race / 等待）；(3) 正確掛進開機流程。
