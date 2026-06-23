# Agent Git Push After Approval (Opt-In)

After a patch is accepted by human approval (the Code Review Agent never
auto-approves; pass still routes to human review), an opt-in `publish` step
lets the agent commit the applied change and push it to a
dedicated per-run branch on a configured remote. This extends the agent
boundary that ADR-0001 deliberately stopped at ("must not commit or push"). The
step is **disabled by default**, so the existing human-owned publish flow stays
the baseline.

Status: **Planned** (not implemented). This ADR records the design before code.

## Context

ADR-0001 keeps commit/push/build/flash entirely human-owned. The
`system architecture.png` diagram, however, shows an `approve → agent git push →
git server` path. Automating publish removes a manual handoff step but moves a
previously human-only, hard-to-reverse action inside the agent, so it must be
explicit, opt-in, and conservative.

## Decision

Add a `publish` node to the LangGraph repair graph, placed **after**
`apply_patch`:

```text
apply_patch (stage=target_ready)
  -> publish        commit + push      (stage=published)
  -> END
```

`publish` runs only when `apply_patch` succeeded, and only when
`AUTO_PUSH_ENABLED=true`. When disabled, the graph behaves exactly as today and
the CLI keeps printing the human handoff message.

### Node contract

- Input: applied working tree, `git_remote`, branch strategy.
- Process: create/switch to `bsp-agent/<run_id>`, commit the agent's change with
  a generated message (run id, attempt, issue summary, changed files), then
  `git push` to the remote. Never `--force`. Never push to `main`/`master`.
- Output: `attempt.published_branch`, `attempt.published_commit`,
  `stage=published` on success or `stage=publish_failed` on error;
  artifact `attempts/<n>/publish.json`.

## Considered Options

- Keep publish human-owned (status quo, ADR-0001).
- **Push to a dedicated per-run branch `bsp-agent/<run_id>` (decided).**
- Push to the current branch or `main` (rejected: pollutes the human's branch).
- Operator-supplied branch name (rejected: needs human input every run, defeats
  the automation; the per-run branch is fully derivable from `run_id`).

## Safety constraints

- `AUTO_PUSH_ENABLED` defaults to `false` (opt-in, like the other agent-boundary flags).
- No stored credentials: rely on the host's existing git credential helper / SSH
  key, consistent with the `SSH Access` rule in `CONTEXT.md`.
- No force-push; dedicated `bsp-agent/<run_id>` branch only.
- `publish_failed` does **not** auto-retry the repair loop: the patch is already
  applied and the failure is in git/network, not in the patch. It surfaces to
  the human instead.
- Build and flash remain human-owned (unchanged from ADR-0001).

## Files to change (when implemented)

| File | Change |
|---|---|
| `agent/tools/git_tools.py` | add `current_branch`, `commit_changes`, `push_branch` (no `--force`) |
| `agent/graph.py` | add `publish_node`; edge `apply_patch -> publish -> END`; `publish_failed` stage |
| `agent/config.py` | add `auto_push_enabled` (default `False`), `git_remote` (default `origin`), branch strategy |
| `agent/state.py` | add `published_branch`, `published_commit`, `publish_status` to the attempt |
| `agent/nodes/workflow.py` | commit-message builder; write `publish.json` |
| `agent/main.py` | the three "Human should commit, push, build, and flash" messages become conditional on `auto_push_enabled` |
| `docs/system-overview.md`, `spec.md`, `CONTEXT.md` | update the "no commit/push" statements to reference this opt-in |

## Resolved decisions

1. **Branch strategy — `bsp-agent/<run_id>` (decided).** The branch name is
   derived from `run_id`; no operator input per run.
3. `publish` requires a clean tree apart from the agent's own change (init-run
   already enforces clean source).

## Open questions (to confirm before implementation)

2. Whether a successful push should also open a PR/MR, or stop at the branch
   (current plan: stop at the branch).

## Consequences

When enabled, the agent owns one more previously human step (publish to a
branch). Build and flash stay human-owned. When disabled (default), behavior is
identical to ADR-0001. The boundary change is therefore additive and reversible
via a single config flag.
