# GitHub Webhook Trigger (v1)

The first automated ingestion path is a GitHub webhook: when an issue is opened
in the configured GitHub repository, GitHub POSTs to a small HTTP server, which
verifies the request and starts one repair run against a single configured local
BSP source repo. This realizes the "git issue -> agent" path from
`docs/system architecture.png` as a push (webhook) instead of a cronjob poll.

Status: **Planned** (not implemented). This ADR records the design before code.

## Context

The agent today is a synchronous CLI (`bsp-agent init-run`). To trigger it from
GitHub issues without a human running the CLI, an HTTP endpoint must receive
GitHub webhook deliveries, authenticate them, and start a run. A webhook handler
has hard constraints that shape the design: it must authenticate the sender, it
must respond within seconds, and deliveries can be duplicated.

## Decision

Add a small FastAPI server exposing `POST /webhook/github`. On an
`issues`/`opened` event it starts a run against a single configured BSP repo.

```text
issue opened
  -> POST /webhook/github
  -> verify HMAC-SHA256 (X-Hub-Signature-256)        reject -> 401
  -> filter: X-GitHub-Event == issues, action == opened   else -> 204
  -> dedupe by X-GitHub-Delivery                     duplicate -> 200
  -> issue.title + body -> issue text; first fenced code block -> log (optional)
  -> record the issue's comments_url in the run state
  -> enqueue background run; respond 202 immediately
  -> [background, serialized] create_run -> graph runs to human_review and STOPS
       (the agent does NOT touch the issue at this point)
  -> human approves with the CLI (bsp-agent review/approve)
  -> apply_patch -> publish (commit + push to bsp-agent/<run_id>)
  -> only after a successful push: post a result comment on the issue
       (run_id, branch, changed files)
```

The agent does not write to the GitHub issue until the human has approved and the
patch is committed and pushed. The issue comment is a *result report*, not a
review request — it never appears before approval. This keeps the outward-facing
action (commenting) behind the same human gate as commit/push.

### Resolved decisions

1. **Target repo**: a single configured local BSP repo (`BSP_REPO_PATH`). No
   per-repo/label mapping in v1.
2. **Log source**: the issue body is the issue text; the first fenced code block
   in the body is extracted as the dmesg log. If there is none, the run proceeds
   without a log.
3. **Human review**: v1 keeps CLI approval. The webhook only triggers the run; it
   does not comment on the issue. A human runs `bsp-agent review/approve`, and
   only after a successful publish (commit + push) does the agent post a result
   comment on the issue. A comment-driven `/approve` webhook is deferred to a
   later version.

### Component layout

```text
agent/server.py    FastAPI app: /webhook/github (+ /health), launches the run
agent/webhook.py   pure helpers: verify_signature, parse_issue_event,
                   extract_log_block (unit-testable without HTTP)
create_run / run_repair_graph   reused unchanged; webhook is just another entry
```

## Security constraints

- HMAC-SHA256 verification of `X-Hub-Signature-256` against
  `GITHUB_WEBHOOK_SECRET`, compared with `hmac.compare_digest`. Missing/invalid
  signature -> 401. This is mandatory; without it anyone can trigger the agent.
- Only `issues`/`opened` is acted on; all other events return 204 and do nothing.
- `GITHUB_TOKEN` (for posting result comments) and the webhook secret are never
  written to logs or run artifacts.

## Operational constraints

- **Fast ack**: GitHub expects a 2xx within ~10s. The handler verifies, enqueues
  a background run, and returns 202 immediately. The run (LLM calls, up to
  human_review) never blocks the HTTP response.
- **Idempotency**: deliveries can repeat. Dedupe by `X-GitHub-Delivery` (a small
  on-disk marker under `runs/`), so one issue does not open duplicate runs.
- **Serialized runs**: all runs share the single `BSP_REPO_PATH` working tree
  (ADR-0001). Concurrent runs would corrupt that tree, so v1 serializes runs with
  a process-wide lock; additional issues queue until the current run reaches
  human_review.
- **Exposure**: GitHub must reach the server from the public internet. Dev uses a
  tunnel (ngrok / cloudflared); production uses a reverse proxy. The internal LLM
  endpoint and the BSP repo stay on the host's network.
- **Clean source precondition**: `init-run` requires a clean working tree; a
  webhook run inherits this. If the repo is dirty, the run fails and the agent
  comments the failure on the issue.

## Considered Options

- **Webhook push (chosen)**: low latency, no polling, but needs a public endpoint.
- Cronjob polling the issues API (the original diagram): no public endpoint, but
  adds latency and API rate-limit handling. Deferred.

## Open questions (later versions)

- Comment-driven approve/reject from the issue thread (`/approve`).
- Per-repo mapping and agent-managed worktrees to allow concurrent runs.
- Replace in-process background tasks with a durable job queue when volume grows.

## Consequences

v1 adds an HTTP surface (FastAPI + uvicorn + an HTTP client for comments) and a
new config block, but reuses the existing run pipeline unchanged. The agent
boundary is unchanged: it still stops at human_review and never builds, flashes,
or auto-approves. The webhook only automates the *trigger*, not the approval.
