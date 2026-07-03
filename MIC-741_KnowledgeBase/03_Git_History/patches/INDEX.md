# Patches 索引 — mic_741_jetpack_7.2

每個檔案 = 一個專案 commit 的完整修改紀錄（commit message + 全量 diff），供本地 LLM 讀取理解。
依時間順序編號 01~32。上游 NVIDIA L4T base（357 個 Chris.Ke commit）未納入（屬基底匯入，非 MIC-741 客製）。

| # | Patch | 日期 | 檔數 | +/- | Subject |
|---|-------|------|------|-----|---------|
| 1 | `01_137db3e_forked-from-mic-743.patch` | 2025-11-27 | 8 | +4322/-14 | Forked from MIC-743 |
| 2 | `02_04b78ab_mdio-fix.patch` | 2025-12-24 | 9 | +21338/-69 | MDIO fix |
| 3 | `03_5138ed6_bsp-v1-0-1.patch` | 2025-12-24 | 3 | +16463/-1 | BSP v1.0.1 |
| 4 | `04_80c608b_bsp-v1-0-2-resolve-10g-aquantia-phy-powe.patch` | 2026-01-13 | 15 | +23237/-16506 | BSP v1.0.2: Resolve 10G Aquantia PHY, power LED, SPI bus and nvpmodel issues. |
| 5 | `05_d867c08_walk-around-nvpmodel-issues-for-mgbe-unl.patch` | 2026-01-15 | 4 | +16/-51 | Walk around nvpmodel issues for MGBE unlink. |
| 6 | `06_12339ac_bsp-v1-0-3-walk-around-nvpmodel-issues-f.patch` | 2026-01-15 | 1 | +1/-1 | BSP v1.0.3: Walk around nvpmodel issues for MGBE unlink. |
| 7 | `07_0b4ad00_unplug-nvpmodel-fix.patch` | 2026-01-16 | 1 | +1/-1 | Unplug NVPModel fix. |
| 8 | `08_b640fe1_update-gitignore.patch` | 2026-01-20 | 1 | +1/-0 | Update gitignore. |
| 9 | `09_84f433e_forked-from-jetpack-7-0.patch` | 2026-02-04 | 1 | +5/-5 | Forked from JetPack 7.0 |
| 10 | `10_6057b31_apply-mic-741-and-117gb-flash-config.patch` | 2026-02-05 | 32 | +4921/-9155 | Apply MIC-741 and 117GB flash config. |
| 11 | `11_c158015_remove-ea-graphic-driver.patch` | 2026-02-05 | 5 | +0/-3 | Remove EA graphic driver. |
| 12 | `12_f1dbd21_enable-can-bus-for-jetpack-7-1.patch` | 2026-02-05 | 2 | +64/-0 | Enable CAN bus for JetPack 7.1. |
| 13 | `13_e9b4042_skip-board-information-check.patch` | 2026-02-05 | 1 | +1/-0 | Skip board information check. |
| 14 | `14_c8f55b4_spi-to-can-bus-frequency-optimize.patch` | 2026-02-09 | 1 | +4/-2 | SPI to CAN bus frequency optimize. |
| 15 | `15_4e2f1bc_refactor-genericize-camera-sipl-download.patch` | 2026-03-09 | 1 | +22/-1 | refactor: genericize Camera SIPL download and add support for v38.4.0 |
| 16 | `16_44338db_fix-revert-mttcan-errors-and-update-mgbe.patch` | 2026-03-09 | 6 | +211/-66 | Fix: revert mttcan errors and update mgbe3 shutdown configuration |
| 17 | `17_b0d95ef_release-update-bsp-to-v1-0-1.patch` | 2026-03-09 | 1 | +1/-1 | release: update BSP to v1.0.1 |
| 18 | `18_025c50c_feat-flash-v1-0-2-add-boot-storage-sh-fo.patch` | 2026-03-24 | 2 | +3/-2 | feat(flash): [v1.0.2] add boot_storage.sh for dynamic NVMe path switching |
| 19 | `19_ea6e486_fix-build-correct-som-filename-in-config.patch` | 2026-03-25 | 1 | +1/-1 | fix(build): correct SoM filename in config.mk |
| 20 | `20_aad8992_fix-mgbe1-rst-pin-gpio-definition-confli.patch` | 2026-05-21 | 1 | +0/-1 | fix MGBE1 RST pin gpio definition conflict |
| 21 | `21_3d3301c_feat-bsp-bring-up-jetpack-7-2-base-l4t-r.patch` | 2026-06-16 | 1 | +9/-9 | feat(bsp): bring up JetPack 7.2 base (L4T r39.2.0) |
| 22 | `22_99d6b3e_config-point-jp7-2-bsp-download-urls-to-.patch` | 2026-06-17 | 1 | +3/-3 | config: point JP7.2 BSP download URLs to internal server |
| 23 | `23_eaf02e9_feat-mic-741-customize-at7a1-board-for-j.patch` | 2026-06-17 | 29 | +5309/-6405 | feat(mic-741): customize AT7A1 board for JetPack 7.2 |
| 24 | `24_9fdb1f0_fix-mic-741-enable-pcie-c3-2nd-nvme-via-.patch` | 2026-06-22 | 1 | +5/-0 | fix(mic-741): enable PCIe-C3 (2nd NVMe) via ODMDATA uphy0-config-6 |
| 25 | `25_d0eeee7_fix-pinmux-restore-i2c3-i2c9-can2-can3-p.patch` | 2026-06-22 | 2 | +38/-34 | fix(pinmux): restore I2C3/I2C9/CAN2/CAN3 pins reset to rsvd on JP7.2 |
| 26 | `26_d04a932_release-v1-0-0-optimize-for-multiple-cor.patch` | 2026-06-22 | 1 | +1/-1 | release: V1.0.0 - Optimize for multiple core compile and fix some bugs. |
| 27 | `27_70ebb17_feat-camera-switch-camera-sipl-to-l4t-r3.patch` | 2026-06-23 | 1 | +5/-1 | feat(camera): switch Camera SIPL to L4T r39.2.0 for JetPack 7.2 |
| 28 | `28_8c36834_chore-framework-bump-framework-commit-to.patch` | 2026-06-23 | 1 | +1/-1 | chore(framework): bump framework_commit to e69a04a7 |
| 29 | `29_9fde196_feat-config-select-som-t5000-t4000-via-b.patch` | 2026-06-24 | 5 | +70/-9 | feat(config): select SoM T5000/T4000 via bsp_som param |
| 30 | `30_927616b_release-v1-0-1-support-t5000-t4000-som-s.patch` | 2026-06-24 | 1 | +1/-1 | release: V1.0.1 - support T5000/T4000 SoM selection via bsp_som |
| 31 | `31_071c674_fix-can-restore-mcp2518fd-interrupt-on-d.patch` | 2026-06-26 | 4 | +325/-2 | fix(can): restore MCP2518FD interrupt + on-demand enable on JP7.2 |
| 32 | `32_81eb09d_chore-release-bump-version-to-v1-0-2.patch` | 2026-06-26 | 1 | +1/-1 | chore(release): bump version to V1.0.2 |
