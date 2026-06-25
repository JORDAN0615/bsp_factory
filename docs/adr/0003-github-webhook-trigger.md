# GitLab Webhook Trigger (v1)

The automated ingestion path is a GitLab Issue Hook: when an issue is opened in
the configured GitLab project, GitLab POSTs to the agent HTTP server. The server
verifies the hook token and starts one repair run against a single configured
local BSP source repo.

Status: **Implemented**.

Note: the existing endpoint path remains `POST /webhook/github` for backward
compatibility with earlier local setup scripts. Its payload and authentication
semantics are GitLab-only.

## Context

The agent can be run synchronously from the CLI, but issue-driven operation needs
an HTTP trigger. The webhook handler must authenticate the sender, respond
quickly, dedupe repeated deliveries, and avoid concurrent access to the single
BSP working tree.

## Decision

Expose a FastAPI server with `POST /webhook/github`. On a GitLab `Issue Hook`
with `object_kind == "issue"` and `object_attributes.action == "open"`, it
starts a run against `BSP_REPO_PATH`.

```text
issue opened
  -> POST /webhook/github
  -> verify X-Gitlab-Token against GITLAB_WEBHOOK_TOKEN       reject -> 401
  -> filter: X-Gitlab-Event == "Issue Hook"                  else -> 204
  -> filter: object_kind == "issue", action == "open"        else -> 204
  -> dedupe by X-Gitlab-Event-UUID                           duplicate -> 200
  -> issue title + description -> issue text
  -> first fenced code block from description -> log (optional)
  -> build issue notes URL:
       <GITLAB_API_URL>/projects/<project.id>/issues/<issue.iid>/notes
  -> record issue_notes_url in the run state
  -> enqueue background run; respond 202 immediately
  -> [background, serialized] create_run -> graph runs to human_review and STOPS
       (the agent does NOT write a note at trigger time)
  -> human approves with the CLI (bsp-agent review/approve)
  -> apply_patch -> publish (commit + push to bsp-agent/<run_id>)
  -> only after a successful push: post a result note through GitLab Notes API
       (run_id, branch, changed files)
```

The agent does not write to the GitLab issue until the human has approved and the
patch is committed and pushed. The issue note is a result report, not a review
request.

## Resolved Decisions

1. **Target repo**: a single configured local BSP repo (`BSP_REPO_PATH`). No
   per-project/label mapping in v1.
2. **Log source**: the issue description is the issue text; the first fenced code
   block in the description is extracted as the dmesg log. If there is no fenced
   block, the run proceeds without a log.
3. **Human review**: v1 keeps CLI approval. The webhook only triggers the run.
   A human runs `bsp-agent review/approve`; only after a successful publish does
   the agent post a result note on the issue.

## Component Layout

```text
agent/server.py          FastAPI app: /webhook/github (+ /health), launches runs
agent/webhook.py         pure helpers: verify_token, build_notes_url,
                         extract_log_block
agent/tools/gitlab_tools.py
                         GitLab Notes API caller
create_run / run_repair_graph
                         reused unchanged; webhook is another entry point
```

## Security Constraints

- GitLab hook token verification uses `X-Gitlab-Token` compared against
  `GITLAB_WEBHOOK_TOKEN` with `hmac.compare_digest`. This is a plain token
  comparison, not an HMAC signature.
- Missing/invalid token -> 401.
- Only GitLab `Issue Hook` events with action `open` are acted on; all other
  events return 204 and do nothing.
- `GITLAB_TOKEN` and the webhook token are never written to logs or run
  artifacts.

## Operational Constraints

- **Fast ack**: the handler verifies, records dedupe/active markers, schedules a
  background task, and returns 202 immediately.
- **Idempotency**: deliveries can repeat. Dedupe by `X-Gitlab-Event-UUID` using
  an on-disk marker under `runs/.webhook/`.
- **Serialized runs**: all webhook runs share the single `BSP_REPO_PATH` working
  tree. While one webhook run is unresolved, additional deliveries return 202
  but do not start a run. The active marker is `runs/.webhook/active`.
- **Exposure**: GitLab must reach the server from the public internet. Dev uses a
  tunnel such as ngrok or cloudflared; production should use a reverse proxy.
- **Clean source precondition**: managed git workflow pulls the configured base
  branch and creates `bsp-agent/<run_id>` before the graph edits files. If this
  fails, the run aborts before creating a run directory.

## Consequences

v1 adds an HTTP surface (FastAPI + uvicorn + GitLab Notes API client) but keeps
the repair graph boundary unchanged: the agent still stops at `human_review` and
does not build, flash, or approve on its own. The webhook automates the trigger,
not the approval.
