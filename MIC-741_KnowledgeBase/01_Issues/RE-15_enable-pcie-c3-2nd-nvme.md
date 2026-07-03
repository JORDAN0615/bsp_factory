# RE-15 — Enable PCIe-C3 (2nd NVMe) via ODMDATA

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `9fdb1f0` |
| 日期 | 2026-06-22 |
| 類型 | FIX / FEATURE |
| 主要檔案 | `source/modify/driver/p3834-0008-p4071-0000-nvme.conf` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
第二顆 NVMe（掛在 PCIe-C3 / UPHY0 lane6-7）未啟用，需透過 ODMDATA 開啟 PCIe-C3 RP。

## 解法（實際 commit 做法）
- 於 nvme.conf 加入 `ODMDATA="uphy0-config-6,pcie@3_status=okay";`。
- 註記：shell 重新賦值時「只有最後一行 active ODMDATA 生效」，多項需合併成單一逗號分隔行。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-15_enable-pcie-c3-2nd-nvme/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`9fdb1f0.patch`。

## 🧪 LLM 試解任務
- 問題：第二顆 NVMe (PCIe-C3) 未啟用，請透過 ODMDATA 開啟。
- 評分重點：(1) 正確的 `uphy0-config-6` + `pcie@3_status=okay`；(2) 是否注意到多個 ODMDATA 需合併為單行（只有最後一行生效）。
