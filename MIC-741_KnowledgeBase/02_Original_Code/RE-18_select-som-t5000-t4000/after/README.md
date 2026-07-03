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

## Output

Package name: `MIC-741_<SoM>_7.2_V<x.y.z>_SDK.tbz2`, e.g.
`MIC-741_T5000_7.2_V1.0.0_SDK.tbz2`, `MIC-741_T4000_7.2_V1.0.0_SDK.tbz2`.

## Jenkins

A job combines two knobs — `url_branch` (test plan) × the `bsp_som` env var (SoM):

```sh
url_branch=master           # or test/25g-pattern
export bsp_som=T4000        # defaults to T5000 if unset
```

`source/config/task_jenkins_build.sh` passes `bsp_som` into each build step as a make
command-line argument.
