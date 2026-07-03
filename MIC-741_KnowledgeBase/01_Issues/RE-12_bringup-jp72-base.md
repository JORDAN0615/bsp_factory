# RE-12 — Bring up JetPack 7.2 base (L4T r39.2.0)

| 欄位 | 內容 |
|---|---|
| 反推來源 commit | `3d3301c` |
| 日期 | 2026-06-16 |
| 類型 | TASK / bring-up |
| 主要檔案 | `source/config/config.mk` |

> 本 issue 由 git history 反推，非 DQA 原始單。

## 問題 / 目標（反推）
從 JetPack 7.1 升級到 **7.2（L4T r39.2.0）** base，需更新 BSP 設定指向新版本。

## 解法（實際 commit 做法，取自 commit message）
- L4T driver/rootfs/source 由 r38.4.0 → r39.2.0。
- kernel local version 改為 `-1021-tegra`，更新 lib module 路徑。
- DTB 路徑改為 `build/nvidia-public/devicetree/generic-dtbs`。
- 7.2 起始版本 `bsp_version=V0.0.1`（driver/kernel 客製待後續）。

## 原始碼
對應程式碼資料夾：`../02_Original_Code/RE-12_bringup-jp72-base/`（含 before/ after/ 與 .patch）
- `before/`、`after/`、`3d3301c.patch`。

## 🧪 LLM 試解任務
- 問題：將 BSP base 由 JP7.1 升級到 JP7.2 (L4T r39.2.0)，請更新 `config.mk` 對應的版本/路徑。
- 評分重點：(1) L4T 版本字串；(2) kernel localversion / module 路徑；(3) DTB 路徑。
