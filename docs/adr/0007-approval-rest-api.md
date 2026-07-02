# Approval REST API for the Review Frontend

Add a small HTTP API to the existing agent server so a web frontend can list runs
waiting for human review, view a run's proposed patch and code review, and approve
or reject it — the same actions the CLI already performs.

Status: **Proposed**.

## Context

Human approval is mandatory and currently CLI-only (`bsp-agent pending / review /
approve / reject`). Once the agent runs in a container, a human has no convenient
way to act except `docker exec`. We want a browser frontend (separate ADR / work)
whose two jobs are: see what is pending, and approve/reject a change. That frontend
needs an HTTP surface.

The approval logic must not be reimplemented. The CLI commands are thin wrappers
over three workflow functions, and the API must wrap the **same** functions so the
human-approval guarantee, the GitLab result note, the run-lock release, and the
checkpointer resume all behave identically:

```text
list_pending_runs(settings)            -> rows for runs at stage human_review
approve_run(run_dir, settings)         -> resume_review_graph(action=approve)
reject_run(run_dir, feedback, settings)-> resume_review_graph(action=reject)
```

## Decision

Add REST endpoints to the existing FastAPI app (`agent/server.py`), each a thin
wrapper over the existing workflow functions. No new approval logic, no new state,
no bypass of any gate.

```text
GET  /api/runs
       -> list_pending_runs(settings)
       200 [{run_id, issue_no, code_review, changed_files, attempt_no}]

GET  /api/runs/{run_id}
       -> BSPAgentState.load(runs_dir/run_id) + read artifacts
       200 {run_id, stage, issue, attempt_no, code_review (code_review.md),
            diff (patch.md), changed_files, repo_inspection}
       404 if the run dir / state does not exist

POST /api/runs/{run_id}/approve
       -> approve_run(runs_dir/run_id, settings)
       200 {run_id, stage, published_branch, changed_files}
       404 unknown run
       409 if approve_run raises (e.g. patch not "generated" / not at human_review)

POST /api/runs/{run_id}/reject   {feedback: str}
       -> reject_run(runs_dir/run_id, feedback, settings)
       200 {run_id, stage, attempt_no}
       400 if feedback is empty
       404 unknown run
       409 if reject_run raises
```

`run_id` resolves to `settings.runs_dir / run_id`; reject paths that escape
`runs_dir` are refused (no `..`, must stay under runs_dir).

## Boundaries

- **No new approval path.** Endpoints call the same functions as the CLI;
  `approve_run` still goes `resume → apply_patch → publish`, still posts the GitLab
  note on a successful push, and still releases the active run-lock on
  `published` / `publish_failed`. The API cannot approve anything the CLI could not.
- **Single replica still holds.** Approval resumes the graph in the server process
  via the on-disk checkpointer; the serialization marker and one-at-a-time design
  are unchanged.
- **Mandatory human approval is unchanged.** The API exposes the human action; it
  does not auto-approve and does not skip code review or validation.

## Out of Scope / Deferred

- **No authentication in phase 1.** The endpoints are unauthenticated, intended for
  an internal network. This is a deliberate, recorded risk: anyone who can reach the
  API can approve a push. Adding a token / basic-auth is a follow-up.
- **The frontend itself** (React + Vite, served separately) is separate work; this
  ADR only defines the HTTP surface it consumes.
- Listing non-pending / historical runs and richer run detail can be added later;
  phase 1 lists only runs at `human_review`.

## Consequences

The webhook server gains a read + approve/reject HTTP surface reusing the existing
workflow functions, so the frontend is a thin client and the CLI keeps working
unchanged. The cost is an unauthenticated control surface (accepted for phase 1,
internal-only) that must be locked down before any non-trusted exposure.
