# BSP Build Environment & Framework Entrypoint Contract

Define **where** the Target build runs and **what** the agent calls to run it,
so the later build-gate nodes (ADR-0019 `target_build`, ADR-0020 `full_bsp_build`)
depend on one stable contract instead of any build internals. This ADR is the
first split-out of the oversized ADR-0017; it covers only the build environment
and the entrypoint contract — no graph wiring, no flashing.

Status: **Proposed** on branch `feat/deep-agent-integration`.

## Context

Three facts, established by inspecting the actual assets on disk:

1. **The build is x86-64 Linux only.** The cross-toolchain in `x-tools/` is
   `aarch64-none-linux-gnu-gcc`, and `file` reports it as
   `ELF 64-bit LSB executable, x86-64, GNU/Linux`. It cannot execute on macOS
   (`exec format error`), and the Linux kernel build needs Linux host tooling
   (`flex`, `bison`, `libssl-dev`, ELF-only kbuild host binaries). The build host
   is therefore an **x86-64 Ubuntu** machine — the user's workstation — never the
   Mac.

2. **The agent runs on that same Ubuntu workstation** (decided this session).
   The build is therefore a **local subprocess**, not an SSH/scp round-trip. The
   staging worktree and the build share one filesystem. (On-target *device*
   validation over SSH is a separate, later concern — ADR-0021.)

3. **Advantech already has a build framework; the agent must reuse it, not
   reinvent it.** The BSP repo the agent patches carries `config/config.mk`, which
   is the config file for an existing in-house framework:

   - `framework_git=git@172.17.4.45:isystem-esg-linux-bsp/framework_ria.git`
     (`framework_ria`, branch `master`) — the build framework.
   - `pchain_git=…/patch_package_list.git` — a patch-package list.
   - `type_docker_base=1` — the build already runs **inside Docker**.
   - Named build flows: `config_kernel_build_type=build_jetpack_7_v2`,
     `config_kernel_install_module=modules_all_jetpack_7_v2`,
     `config_kernel_copy_dtb=dtb_all_v2`; toggles `is_build_kernel/dtb/initrd/nvgpu=1`.
   - Board/target: `bsp_board=MIC-741`, `bsp_som=T5000`, `bsp_jetpack=7.2`,
     `flash_platform=jetson-agx-thor-devkit`, chip `t264` (AGX Thor).
   - Internal fetch URLs for driver/rootfs/source/toolchain (TFTP `172.17.22.195`).

   The agent's repo (`config/`, `driver/`, `kernel/hardware/nvidia/t264/nv-public/…`)
   is the **customization overlay** this framework consumes; its paths mirror the
   NVIDIA tree. So the real MIC-741 build is `framework_ria` driven by `config.mk`
   in Docker — not the generic NVIDIA `make -C kernel` recipe, and not the
   `jetson-build-source` skill (that skill is background *knowledge* for the agent,
   not the build executor).

The consequence: the agent needs exactly one thing from the build side — a way to
say "build this patched tree" and get back pass/fail plus a log. Everything about
*how* the build works already lives in `framework_ria` + `config.mk`.

## Decision

Introduce a single thin **build entrypoint** on the Ubuntu workstation,
`build_bsp.sh`, that wraps the existing `framework_ria` invocation. The agent's
build nodes call only this entrypoint and depend only on its contract.

### Entrypoint contract

```text
build_bsp.sh  <SRC_DIR>  [BUILD_SCOPE]
```

- **`SRC_DIR`** — absolute path to the patched BSP source tree to build. For the
  `target_build` gate this is the agent's detached staging worktree with the diff
  already applied; for `full_bsp_build` it is the real working tree after
  `apply_patch`. Same layout as the agent's repo (`config/`, `driver/`,
  `kernel/hardware/…`) so `config.mk` resolves against it.
- **`BUILD_SCOPE`** (optional) — `dtb` | `kernel` | `full`, mapping to the
  framework's `is_build_*` toggles / `config_kernel_build_type`. Default `full`.
  The fast gate uses the narrowest scope the change implies (a device-tree-only
  fix builds `dtb`); the post-approval build uses `full`.

**Behavioral contract (what the agent relies on):**

| Property | Requirement |
|---|---|
| Exit code | `0` = build succeeded; non-zero = build failed. This is the gate signal. |
| Logs | All build output goes to stdout/stderr; the agent captures it verbatim. A failing build's log is fed back to the deep agent as retry context (ADR-0019). |
| Non-interactive | No prompts, no TTY needs — it runs headless under the agent. |
| Deterministic inputs | Sources/toolchain are pre-fetched (see runbook); a build must not depend on live internet beyond the pre-provisioned internal mirrors. |
| No side effects outside build outputs | It must not push, flash, or write into the agent's git history. Artifacts land where `framework_ria`/`config.mk` put them (e.g. `path_dtb`); promotion/flash is ADR-0020/0021. |
| Isolation-safe | Two builds of different staging trees must not collide (per-invocation build/work dir). |

The entrypoint is **owned by the BSP team**, exactly like `tests/validation/*.sh`
already are. The agent treats it as an opaque, contract-bound executable — the same
model `run_validation_script` already uses for on-target scripts.

### The one input this ADR cannot supply

`framework_ria` lives on the internal GitLab and the workstation, not in this repo,
so the **exact framework build command** must be filled in by the BSP team. The
entrypoint is a ~15-line wrapper around whatever command an engineer runs today to
build this repo with `framework_ria` + `config.mk` (likely a `make <target>` or a
`framework_ria` driver script, executed in the Docker base image because
`type_docker_base=1`). Skeleton:

```bash
#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$1"; BUILD_SCOPE="${2:-full}"
# <<< BSP-TEAM FILL-IN: the real framework_ria invocation >>>
# Reads config.mk from "$SRC_DIR/config", runs in the Docker base image,
# builds per BUILD_SCOPE, exits non-zero on any build failure.
# e.g.  framework_ria/build.sh --config "$SRC_DIR/config/config.mk" --scope "$BUILD_SCOPE"
# Its exit code becomes this script's exit code; its output is the agent's log.
```

## Configuration

```env
# Build host = the Ubuntu workstation the agent runs on. Build is a local subprocess.
BUILD_ENTRYPOINT=/opt/bsp-agent/build_bsp.sh   # the team-owned framework_ria wrapper
BUILD_WORKSPACE_ROOT=/opt/bsp-build            # framework_ria + Linux_for_Tegra + x-tools live here
BUILD_TIMEOUT_SEC=3600
BUILD_DEFAULT_SCOPE=full
```

No SSH/scp settings — the build is local. Device-validation SSH settings stay on
the existing `register_target` / `run_validation` path (ADR-0021).

## Setup runbook (Ubuntu x86-64 workstation)

A checklist to make the environment reproducible for a non-BSP-engineer. Steps 1-5
are one-time; step 6 is the acceptance test that must pass **before** the agent is
allowed to build.

1. **Host packages**: `sudo apt install git build-essential bc flex bison libssl-dev zstd docker.io`.
2. **Clone the framework**: `framework_ria` (branch `master`, pin the commit in
   `config.mk` — currently `019b526e`) and `patch_package_list` from
   `172.17.4.45`, under `$BUILD_WORKSPACE_ROOT`.
3. **Place the BSP inputs**: extract `Linux_for_Tegra/source/*.tbz2` and the
   `x-tools/aarch64-none-linux-gnu/` toolchain into the paths `config.mk` expects
   (`path_kernel`, `config_toolchain_path`, etc.), or let the framework fetch them
   from the internal URLs in `config.mk` (`url_driver` / `url_rootfs` /
   `url_source` / `url_toolchain`).
4. **Docker base image**: build/pull the framework's Docker base
   (`type_docker_base=1`) so the build runs in the pinned container.
5. **Write `build_bsp.sh`**: drop the ~15-line wrapper (skeleton above) at
   `BUILD_ENTRYPOINT`, filling in the real `framework_ria` command from its README.
6. **Acceptance test (known-good baseline)**: check out the BSP repo at a **clean,
   unmodified** commit and run `build_bsp.sh <checkout> full`. It must exit `0` and
   produce the expected artifacts (e.g. the DTB at `path_dtb`). This proves the
   environment independently of the agent; only after it passes should
   ADR-0019/0020 wire the nodes in.

## What this ADR does not cover

- Graph wiring of the build as a gate, and build-failure-as-retry-context — ADR-0019.
- Full build gating the push — ADR-0020.
- Promote + flash/scp to the MIC-741 device + engineer hardware test — ADR-0021.
- `apply_patch` / `publish` ordering — unchanged from today; revisited in ADR-0020.

## Consequences

The agent reuses Advantech's real, already-tested build path, so a patch that
"builds" in the agent is built the same way an engineer builds it — no divergence
from a hand-rolled NVIDIA recipe, and the same artifacts feed flashing later. The
contract (exit code + logs) is deliberately minimal, so the framework can evolve
without touching the agent. The costs: the workstation must carry `framework_ria`,
the Docker base image, and the pre-fetched BSP inputs (heavy, internal-network
dependent); the agent inherits the framework's build latency in its loop; and the
one BSP-specific fill-in (`build_bsp.sh`'s framework command) must come from the BSP
team before ADR-0019 can proceed.
