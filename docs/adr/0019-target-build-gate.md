# Target Build Gate

Wire an automated build between the independent code review and human review: a
patch that passes code review is built on a throwaway staging worktree before a
human ever sees it, and a build failure loops back to a new attempt with the build
log as retry context. Second split-out of ADR-0017; depends on the ADR-0018
`build_bsp.sh` entrypoint contract.

Status: **Proposed / implemented behind `TARGET_BUILD_ENABLED=false`** on branch
`feat/deep-agent-integration`.

## Context

Before this ADR the graph went `code_review_agent -> human_review` with no build in
the loop. The strongest correctness signal for a BSP patch — *does it cross-compile*
— only appeared when an engineer built manually, long after the run. A patch that
does not compile could reach a human reviewer, and the compiler error that would
teach the agent what it got wrong was discarded.

ADR-0018 established that the build runs on the Ubuntu workstation (where the agent
now runs) as a local subprocess, via the team-owned `build_bsp.sh` entrypoint whose
only contract is exit code + logs.

## Decision

Insert a `target_build` node on the code-review-pass edge, gated by
`TARGET_BUILD_ENABLED` (default off):

```text
code_review_agent
   reject -> classify_error (new attempt, unchanged)
   pass   -> target_build            (when TARGET_BUILD_ENABLED)
          -> human_review            (when disabled — current behavior)

target_build
   built OK        -> human_review
   built + failed  -> classify_error (new attempt; build log = retry context)
                      -> human_review (only if the retry budget is exhausted)
   could not start -> human_review    (infra pause; does not spend an attempt)
```

### Build execution (`agent/tools/bsp_build.py`)

`run_bsp_build` applies `diff_text` to a fresh detached staging worktree (the real
tree stays clean until human approval), runs `BUILD_ENTRYPOINT <staging> <scope>`
with a timeout, captures stdout+stderr to the attempt's `build.log`, and returns a
`BuildResult(ok, ran, returncode, log_path)`. The staging worktree is always
removed in `finally`.

`ran` separates two failure classes:

- **built and failed** (`ran=True`, non-zero exit) — a normal repair signal. The
  node opens a new attempt (respecting `max_loops`) so the deep agent retries with
  the failure in context.
- **could not start** (`ran=False` — missing entrypoint, timeout, staging/apply
  error) — an infrastructure problem the agent cannot fix by re-editing, so it
  pauses for a human (`failure_reason` set) without spending a repair attempt.

### Retry context (`agent/tools/retry_tools.py`)

A failed attempt now renders its build status and the tail of `build.log` in the
retry context, under "Build failure (fix this before re-editing)", so the next deep
agent attempt sees the exact compiler/boot error. This is the teaching loop.

### State (`agent/state.py`)

`RepairAttempt` gains `build_status` (`success`/`failed`), `build_scope`, and
`build_log_path`; `Stage` gains `target_build`.

## Configuration

```env
TARGET_BUILD_ENABLED=false          # default off; enable after host verification
BUILD_ENTRYPOINT=scripts/build_bsp.sh
BUILD_TIMEOUT_SEC=3600
BUILD_DEFAULT_SCOPE=full
```

`BUILD_ENTRYPOINT` inherits `FRAMEWORK_RIA_DIR` / `FRAMEWORK_PROJECT_DIR` from the
process environment (ADR-0018). With the flag off, the graph is byte-for-byte the
prior `code_review -> human_review` flow.

## What this ADR does not cover

- Post-approval full build gating the push — ADR-0020 (`apply -> full build -> push`).
- Mapping `BUILD_DEFAULT_SCOPE` (`dtb`/`kernel`/`full`) onto framework build flags —
  reserved until confirmed on the host; today the project's `config.mk` decides.
- Device deploy + engineer hardware test — ADR-0021.

## Consequences

Humans review only patches that already build, and build failures become in-run
feedback the agent learns from instead of post-hoc engineer discoveries. The cost is
real cross-compile latency inside the repair loop and a dependency on a provisioned,
verified build host. The default-off flag and the untouched approval boundaries keep
the change reversible and comparable against the current pipeline.
