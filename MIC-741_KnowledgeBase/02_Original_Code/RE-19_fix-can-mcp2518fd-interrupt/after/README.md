# MIC-741 BSP — JetPack 7.2

Advantech MIC-741 (AGX Thor carrier AT7A1) BSP for JetPack 7.2 (L4T r39.2.0 / Tegra264).
A single code base targets both the **T5000** and **T4000** SoMs via a build parameter,
while test plans are switched by git branch.

## Two axes

| Axis | Switched by | Values |
|------|-------------|--------|
| SoM  | build parameter `bsp_som` | `T5000` (default) / `T4000` |
| Test plan | git branch | `master` (baseline) / `test/*` (e.g. 25G pattern) |

The two are orthogonal: any branch can be built against any `bsp_som`.

## Build

```sh
sudo make                  # default T5000
sudo make bsp_som=T4000    # T4000
```

`bsp_som` only selects the SoM-dependent fields, defined in `source/config/som/<som>.mk`:

| Field | T5000 | T4000 |
|-------|-------|-------|
| `file_dtb` | …+p3834-0008-nv.dtb | …+p3834-0000-nv.dtb |
| `flash_platform` | jetson-agx-thor-devkit | jetson-agx-thor-t4000 |

Everything else is shared in `source/config/config.mk`. To add a new SoM, drop in another
`source/config/som/*.mk`.

### Switching SoM in the same workspace

The prepare/base stages are cached and the kernel build container is named per `bsp_som`
(`nvidia_jetson_<som>_jetpack_7.2_kernel`), so an in-place switch needs that stage rebuilt:

```sh
sudo rm -rf build/task        # force prepare/base to re-run for the new SoM
sudo make bsp_som=T4000
```

Both Thor SoMs share the same kernel, so as a faster shortcut you can re-tag the existing
container instead of a full rebuild:

```sh
sudo docker tag nvidia_jetson_t5000_jetpack_7.2_kernel nvidia_jetson_t4000_jetpack_7.2_kernel
sudo make bsp_som=T4000
```

Jenkins is unaffected: each job starts from a clean workspace, so prepare runs fresh per SoM.

## Output

Package name: `MIC-741_<SoM>_7.2_V<x.y.z>_SDK.tbz2`, e.g.
`MIC-741_T5000_7.2_V1.0.0_SDK.tbz2`, `MIC-741_T4000_7.2_V1.0.0_SDK.tbz2`.

## CAN bus

CAN (SPI-CAN, MCP2518FD) is **disabled by default** for autonomous-driving safety and is
enabled on demand. `can_enable.sh` is pre-installed in the default user's home (seeded via
`source/modify/driver/rootfs/etc/skel/`, so it lands in `/home/mic-741/` at build time):

```sh
sudo ~/can_enable.sh        # configures expanders, brings up can0/can1 (CAN-FD), applies INT workaround
```

The script also applies a required runtime work-around for the held-low interrupt line; see
[docs/can-bus-pinmux-interrupt.md](docs/can-bus-pinmux-interrupt.md) for the full root-cause
analysis (includes the build-time MB1 BCT pinmux `enable-input` fix that must also be in the
flashed image).

## Jenkins

A job combines two knobs — `url_branch` (test plan) × the `bsp_som` env var (SoM):

```sh
url_branch=master           # or test/25g-pattern
export bsp_som=T4000        # defaults to T5000 if unset
```

`source/config/task_jenkins_build.sh` passes `bsp_som` into each build step as a make
command-line argument.
