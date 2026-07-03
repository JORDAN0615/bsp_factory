# RE-INDEX — 由 Git History 反推的 Issues

從 `03_Git_History`（repo `mic_741_jetpack_7.2` 的 32 個專案 commit）反推出的 issue 單。
- Issue 單（本資料夾）：`RE-NN_<slug>.md`
- 對應程式碼（before/after + .patch）：`../02_Original_Code/RE-NN_<slug>/`

> 與 DQA 實際 bug 單（`ISSUE-G42005`、`ISSUE-G42006`）的差異：`RE-` 系列為**從 commit 反推的推測性 issue**，問題描述為反向推論，供本地 LLM 試解/評測參考。

## Issue 清單（19 張，依時間）
| RE | commit | 日期 | 類型 | 標題 | 程式碼 |
|----|--------|------|------|------|--------|
| [RE-01](RE-01_mdio-fix.md) | `04b78ab` | 2025-12-24 | FIX | MDIO / Ethernet PHY bring-up | [code](../02_Original_Code/RE-01_mdio-fix/) |
| [RE-02](RE-02_apply-mic741-117gb-flash-config.md) | `6057b31` | 2026-02-05 | CONFIG | Apply MIC-741 + 117GB NVMe flash config | [code](../02_Original_Code/RE-02_apply-mic741-117gb-flash-config/) |
| [RE-03](RE-03_remove-ea-graphic-driver.md) | `c158015` | 2026-02-05 | CHANGE | Remove EA GPU display driver | [code](../02_Original_Code/RE-03_remove-ea-graphic-driver/) |
| [RE-04](RE-04_enable-canbus-jp71.md) | `f1dbd21` | 2026-02-05 | FEATURE | Enable CAN bus (JP7.1) | [code](../02_Original_Code/RE-04_enable-canbus-jp71/) |
| [RE-05](RE-05_skip-board-info-check.md) | `e9b4042` | 2026-02-05 | FIX | Skip board EEPROM/info check (flash) | [code](../02_Original_Code/RE-05_skip-board-info-check/) |
| [RE-06](RE-06_spi-canbus-frequency.md) | `c8f55b4` | 2026-02-09 | FIX | SPI-CAN MCP2518FD clock too high | [code](../02_Original_Code/RE-06_spi-canbus-frequency/) |
| [RE-07](RE-07_camera-sipl-genericize.md) | `4e2f1bc` | 2026-03-09 | REFACTOR | Genericize Camera SIPL download | [code](../02_Original_Code/RE-07_camera-sipl-genericize/) |
| [RE-08](RE-08_revert-mttcan-mgbe3-shutdown.md) | `44338db` | 2026-03-09 | FIX | Revert mttcan errors + MGBE3 shutdown | [code](../02_Original_Code/RE-08_revert-mttcan-mgbe3-shutdown/) |
| [RE-09](RE-09_boot-storage-nvme-switch.md) | `025c50c` | 2026-03-24 | FEATURE | boot_storage.sh dynamic NVMe switching | [code](../02_Original_Code/RE-09_boot-storage-nvme-switch/) |
| [RE-10](RE-10_fix-som-filename.md) | `ea6e486` | 2026-03-25 | FIX | Wrong SoM filename in config.mk | [code](../02_Original_Code/RE-10_fix-som-filename/) |
| [RE-11](RE-11_fix-mgbe1-rst-gpio-conflict.md) | `aad8992` | 2026-05-21 | FIX | MGBE1 RST pin GPIO conflict | [code](../02_Original_Code/RE-11_fix-mgbe1-rst-gpio-conflict/) |
| [RE-12](RE-12_bringup-jp72-base.md) | `3d3301c` | 2026-06-16 | TASK | Bring up JetPack 7.2 base (r39.2.0) | [code](../02_Original_Code/RE-12_bringup-jp72-base/) |
| [RE-13](RE-13_internal-bsp-download-url.md) | `99d6b3e` | 2026-06-17 | CONFIG | Internal BSP download mirror | [code](../02_Original_Code/RE-13_internal-bsp-download-url/) |
| [RE-14](RE-14_customize-at7a1-jp72.md) | `eaf02e9` | 2026-06-17 | FEATURE | Customize AT7A1 board for JP7.2 | [code](../02_Original_Code/RE-14_customize-at7a1-jp72/) |
| [RE-15](RE-15_enable-pcie-c3-2nd-nvme.md) | `9fdb1f0` | 2026-06-22 | FIX | Enable PCIe-C3 (2nd NVMe) via ODMDATA | [code](../02_Original_Code/RE-15_enable-pcie-c3-2nd-nvme/) |
| [RE-16](RE-16_fix-pinmux-i2c-can-rsvd.md) | `d0eeee7` | 2026-06-22 | FIX | I2C/CAN bus timeout (pinmux rsvd) | [code](../02_Original_Code/RE-16_fix-pinmux-i2c-can-rsvd/) |
| [RE-17](RE-17_camera-sipl-r3920.md) | `70ebb17` | 2026-06-23 | CONFIG | Camera SIPL → L4T r39.2.0 | [code](../02_Original_Code/RE-17_camera-sipl-r3920/) |
| [RE-18](RE-18_select-som-t5000-t4000.md) | `9fde196` | 2026-06-24 | FEATURE | Select SoM T5000/T4000 via bsp_som | [code](../02_Original_Code/RE-18_select-som-t5000-t4000/) |
| [RE-19](RE-19_fix-can-mcp2518fd-interrupt.md) | `071c674` | 2026-06-26 | FIX | CAN dead: MCP2518FD interrupt fix | [code](../02_Original_Code/RE-19_fix-can-mcp2518fd-interrupt/) |

## 未納入的 commit（純發版/雜務/fork，無「問題」可反推）
`137db3e`(fork MIC-743)、`5138ed6`(v1.0.1)、`12339ac`(v1.0.3)、`b640fe1`(gitignore)、`84f433e`(fork JP7.0)、`b0d95ef`(release)、`d04a932`(V1.0.0)、`8c36834`(bump framework)、`927616b`(V1.0.1)、`81eb09d`(V1.0.2)。

> `80c608b`/`d867c08`/`0b4ad00` 對應 DQA 實際單，已在 [`ISSUE-G42005`](ISSUE-G42005_GPU-nvpmodel.md) / [`ISSUE-G42006`](ISSUE-G42006_LAN-MGBE.md) 處理，不重複。
