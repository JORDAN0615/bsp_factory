# Agent-Managed Git Workflow (pull, branch, commit, push)

When the agent owns git (`AUTO_PUSH_ENABLED`), a run now manages the full git
lifecycle on the single configured BSP repo: at run start it syncs the configured
base branch to latest and creates the per-run work branch *before* any edit, so
the patch is always proposed against up-to-date source and lands on its own
branch. To keep this safe on a single working tree, webhook runs are processed
strictly one at a time.

Status: **Planned** (not implemented). Builds on ADR-0002 (push) and ADR-0003
(webhook). Extends ADR-0001's "direct working tree" with a managed branch.

## Context

Today `create_run` only requires a clean working tree; it never pulls, and the
per-run branch is created at publish time (after approval). For a webhook-driven
flow this is wrong: the local repo can be stale, so patches get proposed against
old source, and the pushed branch is based on an old commit. Standard practice is
pull latest -> branch -> edit -> review -> push.

The branch-at-start choice interacts with ADR-0001's single working tree: the run
holds the repo on its work branch across the human_review pause, so a second
concurrent run would move the shared repo to a different branch and corrupt the
first. v1 resolves this by serializing webhook runs end to end, not by adopting
git worktrees (deferred).

## Decision

Gate the managed git lifecycle on `AUTO_PUSH_ENABLED` (it already means "the agent
owns push"; it now means the agent owns pull/branch/commit/push). When enabled:

```text
run start (create_run):
  1. ensure clean source
  2. checkout BSP_BASE_BRANCH (if set; else current branch is the base)
  3. git pull --ff-only <remote> <base>     pull fails -> ABORT the run
  4. checkout -b bsp-agent/<run_id>          work branch created BEFORE any edit
  ... inspect / propose patch (on the work branch) ...
apply_patch (after approve): apply the diff on the work branch
publish: commit + push the work branch (it already exists)
terminal without a published patch (report): checkout base, delete the empty
  work branch (no dangling branches)
```

When `AUTO_PUSH_ENABLED` is off, behavior is unchanged: clean gate only, no pull,
no agent branch, human owns all git.

### Resolved decisions

1. **Base**: a configured `BSP_BASE_BRANCH` (e.g. a BSP version branch or `main`).
   Empty means "use the currently checked-out branch as the base".
2. **Branch timing**: the work branch `bsp-agent/<run_id>` is created at run start,
   before any edit.
3. **Pull failure** (offline / no remote / non-fast-forward): abort the run; do not
   propose a patch against stale source. `--ff-only` avoids surprise merges.
4. **Concurrency**: strict one-at-a-time. A webhook run holds the repo from start
   until it is resolved (published, publish_failed, or report). While a run is
   unresolved, the server rejects new webhook deliveries (logged; the issue is not
   started). Enforced by an on-disk marker `runs/.webhook/active`.

## Considered Options

- Pull + branch at start, single tree, strict serialization (**chosen**).
- Keep the current "branch at publish", add pull only (rejected: user wants the
  work branch isolated from the first edit).
- Per-run `git worktree` for true concurrency (**deferred** to a later ADR; the
  proper long-term fix, larger change to ADR-0001).

## Safety / operational constraints

- `git pull --ff-only` only; never an implicit merge or rebase.
- Abort leaves the repo on the base branch, clean; no partial state.
- The active-run marker must be cleared on every terminal transition
  (`approve_run` -> published, `reject_run`/`create_run` -> report,
  publish_failed). A stale marker blocks all new runs; provide
  `bsp-agent unlock` (or document deleting `runs/.webhook/active`) as the manual
  recovery.
- Empty work branches from no-patch / rejected runs are deleted on cleanup.

## Files to change (when implemented)

| File | Change |
|---|---|
| `agent/config.py` | add `bsp_base_branch` (alias `BSP_BASE_BRANCH`, default "") |
| `agent/tools/git_tools.py` | add `pull_ff_only`, `delete_branch`, `branch_exists` |
| `agent/nodes/workflow.py` | managed prep in `create_run` (checkout base, pull, work branch); branch cleanup on report; clear active marker on terminal |
| `agent/graph.py` | `publish_node` already tolerates a pre-existing branch; no change needed beyond confirming it does not re-create |
| `agent/server.py` | reject webhook while the active marker is present; set marker for a started run |
| docs | update ADR-0001/0003 references; system-overview git section |

## Consequences

When `AUTO_PUSH_ENABLED` is on, the agent proposes patches against fresh source on
an isolated per-run branch and pushes it — the workflow a developer would do by
hand. The cost is strict one-at-a-time webhook processing on the single working
tree. True concurrency waits for per-run git worktrees in a later version. When
the flag is off, nothing changes.
