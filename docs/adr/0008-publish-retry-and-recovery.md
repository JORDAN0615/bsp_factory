# Publish Retry and Recovery

When the publish step (commit + push of `bsp-agent/<run_id>`) fails, provide a way
to retry just the publish from the frontend, and a way to abandon a failed run so it
stops blocking new runs. Also fix the locale bug that caused publish to fail
spuriously.

Status: **Proposed**.

## Context

`publish_node` applies the approved patch to the working tree, commits it on a
work branch `bsp-agent/<run_id>`, and pushes. When push (or commit) fails, the run
ends at `publish_failed`. Two problems then occur:

1. **No retry.** A transient or fixable failure (network, branch already exists,
   auth) wastes the whole run; there is no way to re-attempt only the push.
2. **It blocks everything.** If the failure happens before the commit, the working
   tree is left dirty, so the next run's `ensure_clean_source` raises and every
   future issue fails until a human manually cleans the repo.

### Root-cause bug found

The observed failure was not auth/cert. `publish_node` handles an existing branch
with `if "already exists" not in str(exc): raise`, but git on this host is
localized (Chinese): the message is `已有同名…分支`, which does not contain the
English `already exists`. The guard therefore re-raised and publish failed. `run_git`
runs git without forcing a locale, so any English-string match on git output is
unreliable.

## Decision

Three changes.

### 1. Force a stable git locale (bug fix, do first)

`run_git` (and the direct `git apply` subprocess calls in `patch_tools.py`) run git
with `LC_ALL=C` / `LANG=C` in the environment, so git output and error messages are
always English and the existing string matches (`already exists`, etc.) work
regardless of the host locale.

### 2. Shared publish function + retry endpoint

The publish core (checkout work branch, commit, push, set
`publish_status`/`publish_error`/stage) is a single function called by **both** the
graph node and a new API endpoint — the same pattern as `approve_run` (CLI + API
share one function). The graph node does not call an HTTP API.

```text
_do_publish(state, settings)        core: checkout/commit/push, sets stage
publish_node                        calls _do_publish during a run
publish_run(run_dir, settings)      loads state, calls _do_publish, and on
                                    "published" posts the GitLab note + releases the
                                    run lock (like approve_run); returns state

POST /api/runs/{run_id}/publish     -> publish_run; valid only when the run is at
                                       publish_failed (else 409)
                                       200 {stage, published_branch, publish_error}
```

Frontend: when a run's stage is `publish_failed`, show a **Retry push** button plus
the `publish_error` text; on success show the published branch.

### 3. Abandon / recover endpoint

For a `publish_failed` run the human decides not to retry (e.g. the commit itself
failed and the tree is dirty), provide a way to discard the work and return the BSP
repo to a clean base so new runs are not blocked.

```text
POST /api/runs/{run_id}/abandon     -> revert working tree to the base branch,
                                       drop the work branch (_cleanup_managed_branch),
                                       set stage = report, release the run lock
                                       200 {stage}
```

Frontend: an **Abandon** button next to Retry push on a `publish_failed` run.

## Boundaries

- No new approval path; retry/abandon only act on runs already at `publish_failed`
  (the human already approved). They do not re-open review or re-apply patches.
- `_do_publish` is shared by the node and `publish_run`; the node never calls the
  API. Both call the same function — the `approve_run` pattern.
- No auth in phase 1 (consistent with ADR-0007); internal use only.

## Consequences

A failed push is recoverable from the UI (retry) or clearable (abandon) instead of
wedging the single BSP working tree. The locale fix removes a class of spurious
git-error mishandling. The publish logic stays in one shared function with two
callers (graph node, API), so behavior cannot drift between an in-run publish and a
manual retry.
