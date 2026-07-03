# RE-02 — Apply MIC-741 board config + 117GB NVMe flash layout

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `6057b31` |
| 日期 | 2026-02-05 |
| 類型 | CONFIG / board bring-up |
| 主要檔案 | bootloader BCT/bpmp dts、`*-nvme.conf`、`t264.conf.common`、`tegra264-p4071-0000.dtsi`、`defconfig` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
將通用 Jetson 設定客製為 **MIC-741** 板，並建立 **117GB NVMe** 燒錄分割/容量配置；移除不需要的 mttcan HAL 檔。

## 解法（實際 commit 做法）
- 調整 BCT prod / bpmp dts、pinmux/gpio dtsi 為 MIC-741 板腳位。
- 更新 `p3834-0008-p4071-0000-nvme.conf` 與新增 `t264.conf.common` 以套用 117GB flash 配置。
- 更新 defconfig、移除 `m_ttcan.c`、調整 conftest。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-02_apply-mic741-117gb-flash-config/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`6057b31.patch`。

## 🧪 LLM 試解任務
- 輸入：`before/` + 問題。
- 問題：請將設定客製為 MIC-741 並建立 117GB NVMe 燒錄配置。
- 評分重點：(1) nvme.conf / flash 容量配置；(2) 板級 pinmux/dtsi；(3) 與 `after/` 對照（此為大型 config 任務，著重方向正確性）。
