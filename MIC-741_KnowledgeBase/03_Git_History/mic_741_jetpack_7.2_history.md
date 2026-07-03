# Git History 整理 — mic_741_jetpack_7.2

- Repo: https://172.17.4.45/isystem-esg-linux-bsp/mic_741_jetpack_7.2
- 整理日期：2026-06-29
- 總 commit：389（其中專案開發 32 個由 Alex Hsu；其餘 357 個為上游 NVIDIA L4T base，作者 Chris.Ke）
- 時間範圍：2021-08-23（上游 base）～ 2026-06-26
- 原始 log：[`_raw/git_history_7.2_full.txt`](../_raw/git_history_7.2_full.txt)、[`_raw/git_history_7.2_project_commits.txt`](../_raw/git_history_7.2_project_commits.txt)
- **完整修改紀錄（每個 commit 的全量 diff）**：[`patches/`](patches/) — 32 個專案 commit 各一個 `.patch`，索引見 [`patches/INDEX.md`](patches/INDEX.md)。供本地 LLM 逐一讀取理解每次變更內容。

> 血緣：MIC-743 → fork → **MIC-741 (JetPack 7.0)** → fork → **JetPack 7.1** → fork → **JetPack 7.2 (L4T r39.2.0)**。
> 因此本 repo 早期 commit（2025-11 ~ 2026-01）與 `mic_741_at7a1_jetpack_7.0` 共用，包含 G42005 / G42006 兩張 issue 的修正。

---

## 階段一：MIC-741 JetPack 7.0 base（2025-11 ~ 2026-01）
共用基礎，含 DQA issue 修正。

| Commit | 日期 | 說明 |
|--------|------|------|
| `137db3e` | 2025-11-27 | Forked from MIC-743 |
| `04b78ab` | 2025-12-24 | MDIO fix |
| `5138ed6` | 2025-12-24 | **BSP v1.0.1** |
| `80c608b` | 2026-01-13 | **BSP v1.0.2**：Resolve 10G Aquantia PHY, power LED, SPI bus, nvpmodel issues → **對應 ISSUE G42005** |
| `d867c08` | 2026-01-15 | Walk around nvpmodel issues for MGBE unlink → **對應 ISSUE G42006** |
| `12339ac` | 2026-01-15 | **BSP v1.0.3**：同上（版號 bump） |
| `0b4ad00` | 2026-01-16 | Unplug NVPModel fix → **ISSUE G42006 後續** |
| `b640fe1` | 2026-01-20 | Update gitignore |

## 階段二：JetPack 7.1 客製（2026-02 ~ 2026-03）
| Commit | 日期 | 說明 |
|--------|------|------|
| `84f433e` | 2026-02-04 | Forked from JetPack 7.0 |
| `6057b31` | 2026-02-05 | Apply MIC-741 and 117GB flash config |
| `c158015` | 2026-02-05 | Remove EA graphic driver |
| `f1dbd21` | 2026-02-05 | Enable CAN bus for JetPack 7.1 |
| `e9b4042` | 2026-02-05 | Skip board information check |
| `c8f55b4` | 2026-02-09 | SPI to CAN bus frequency optimize |
| `4e2f1bc` | 2026-03-09 | refactor: genericize Camera SIPL download, add v38.4.0 support |
| `44338db` | 2026-03-09 | Fix: revert mttcan errors, update mgbe3 shutdown config |
| `b0d95ef` | 2026-03-09 | **release: BSP v1.0.1** |
| `025c50c` | 2026-03-24 | feat(flash): [v1.0.2] add boot_storage.sh for dynamic NVMe path switching |
| `ea6e486` | 2026-03-25 | fix(build): correct SoM filename in config.mk |
| `aad8992` | 2026-05-21 | fix MGBE1 RST pin gpio definition conflict |

## 階段三：JetPack 7.2 bring-up（2026-06，L4T r39.2.0）
| Commit | 日期 | 說明 |
|--------|------|------|
| `3d3301c` | 2026-06-16 | feat(bsp): bring up JetPack 7.2 base (L4T r39.2.0) |
| `99d6b3e` | 2026-06-17 | config: point JP7.2 BSP download URLs to internal server |
| `eaf02e9` | 2026-06-17 | feat(mic-741): customize AT7A1 board for JetPack 7.2 |
| `9fdb1f0` | 2026-06-22 | fix(mic-741): enable PCIe-C3 (2nd NVMe) via ODMDATA uphy0-config-6 |
| `d0eeee7` | 2026-06-22 | fix(pinmux): restore I2C3/I2C9/CAN2/CAN3 pins reset to rsvd on JP7.2 |
| `d04a932` | 2026-06-22 | **release: V1.0.0** — multi-core compile optimize + bug fixes |
| `70ebb17` | 2026-06-23 | feat(camera): switch Camera SIPL to L4T r39.2.0 for JetPack 7.2 |
| `8c36834` | 2026-06-23 | chore(framework): bump framework_commit to e69a04a7 |
| `9fde196` | 2026-06-24 | feat(config): select SoM T5000/T4000 via bsp_som param |
| `927616b` | 2026-06-24 | **release: V1.0.1** — support T5000/T4000 SoM selection via bsp_som |
| `071c674` | 2026-06-26 | fix(can): restore MCP2518FD interrupt + on-demand enable on JP7.2 |
| `81eb09d` | 2026-06-26 | **chore(release): bump version to V1.0.2** (HEAD) |

---

## 技術主題索引
- **CAN bus**：`f1dbd21`、`c8f55b4`、`44338db`、`d0eeee7`、`071c674`（MCP2518FD / mttcan）
- **MGBE / 10G LAN**：`80c608b`、`d867c08`、`44338db`、`aad8992`
- **nvpmodel / power plan**：`80c608b`、`d867c08`、`0b4ad00`
- **Camera SIPL**：`4e2f1bc`、`70ebb17`
- **Flash / NVMe storage**：`6057b31`、`025c50c`、`9fdb1f0`
- **SoM 選型 (T5000/T4000)**：`9fde196`、`927616b`
- **Pinmux / GPIO**：`d0eeee7`、`aad8992`
