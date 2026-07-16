# Jetson BSP Repair Agent

Controlled workflow agent for Jetson BSP source repair.

The agent takes a BSP issue plus logs, selects relevant Jetson BSP skills, inspects
the configured source repo, proposes a conservative patch, runs an independent code
review pass, then stops for human approval before applying the patch. Build and
flash stay human-owned.

## What It Does

```text
issue / boot log
  -> classify_error
  -> select_skills
  -> load selected SKILL.md files only
  -> retrieve MIC-741 knowledge (optional)
  -> inspect_repo -> patch_agent
     OR Deep Patch Agent (experimental, combines inspection + staged editing)
  -> validate_patch with git apply --check
  -> code_review_agent
  -> human_review interrupt
  -> apply_patch after approval
  -> optional publish to bsp-agent/<run_id>
  -> human builds/flashes
  -> optional SSH validation scripts
  -> report
```

Core safety rule:

```text
The LLM may propose patches, but human approval is required before any patch is applied.
```

## Current Architecture

Main files:

```text
agent/main.py              CLI commands
agent/server.py            FastAPI webhook server
agent/graph.py             LangGraph repair graph
agent/nodes/workflow.py    workflow facade, run lifecycle, reports, publish helpers
agent/tools/llm_tools.py   single LLM choke point
agent/tools/review_tools.py
                           Code Review Agent
agent/observability.py     Langfuse tracing wrapper
agent/tools/gitlab_tools.py
                           GitLab Notes API client
skills/                    Jetson BSP skills
runs/<run_id>/             durable run state and artifacts
```

The LangGraph flow is deterministic around the LLM calls:

```text
classify_error
  -> select_skills          LLM chooses which skill folders to load
  -> load_skill
  -> retrieve_mic741_knowledge
  -> inspect_repo -> patch_agent
     OR deep_patch_agent     Deep Agents plans, reads, delegates, and edits staging
  -> validate_patch         deterministic patch validation only
  -> code_review_agent      independent LLM review
  -> human_review           LangGraph interrupt
  -> apply_patch
  -> publish                no-op unless AUTO_PUSH_ENABLED=true
```

Each run stores:

```text
runs/<run_id>/state.json
runs/<run_id>/checkpoints.sqlite
runs/<run_id>/input.md
runs/<run_id>/raw_logs/
runs/<run_id>/attempts/001/
runs/<run_id>/report.md
```

## Setup

This repo uses Python 3.11+.

```bash
uv sync --extra dev
cp .env.example .env
```

If you are not using `uv`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Configure `.env`:

```env
LLM_BASE_URL=http://your-openai-compatible-server/v1
LLM_API_KEY=EMPTY
LLM_MODEL=your-model

# Experimental replacement for inspect_repo + patch_agent. Default off.
DEEP_AGENT_ENABLED=false
DEEP_AGENT_RECURSION_LIMIT=60

AUTO_PUSH_ENABLED=false
GIT_REMOTE=origin
BSP_BASE_BRANCH=

GITLAB_WEBHOOK_TOKEN=replace-with-webhook-token
GITLAB_TOKEN=replace-with-a-token-that-can-comment
GITLAB_API_URL=https://gitlab.com/api/v4
BSP_REPO_PATH=/path/to/local/bsp/source/repo

LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

`BSP_REPO_PATH` is a local git working tree, not a GitLab/GitHub URL.

The Deep Agent path is described in
[`docs/adr/0016-deep-agent-patch-stage.md`](docs/adr/0016-deep-agent-patch-stage.md).
It edits only a detached staging worktree. The deterministic validation, independent
code review, human approval, apply, and publish stages remain unchanged.

## CLI Usage

Start a run manually:

```bash
.venv/bin/bsp-agent init-run \
  --repo /path/to/local/bsp/source/repo \
  --issue "camera probe failed with i2c -121" \
  --log ./dmesg.txt
```

Review pending runs:

```bash
.venv/bin/bsp-agent pending
```

Inspect and approve/reject:

```bash
.venv/bin/bsp-agent review --run runs/<run_id>
.venv/bin/bsp-agent approve --run runs/<run_id>
.venv/bin/bsp-agent reject --run runs/<run_id> --feedback "explain what to change"
```

After approval, if `AUTO_PUSH_ENABLED=false`, the patch is applied locally and the
human owns commit/push/build/flash.

Register a flashed target and run validation scripts:

```bash
.venv/bin/bsp-agent register-target \
  --run runs/<run_id> \
  --ssh-target nvidia@192.168.1.50 \
  --git-ref abc1234

.venv/bin/bsp-agent run-tests \
  --run runs/<run_id> \
  --script camera_check.sh

.venv/bin/bsp-agent report --run runs/<run_id>
```

Validation scripts live under:

```text
tests/validation/
```

## Git Workflow

Default behavior:

```text
AUTO_PUSH_ENABLED=false
```

The agent applies the approved patch to the local working tree only. A human
commits, pushes, builds, and flashes.

Opt-in managed publish:

```env
AUTO_PUSH_ENABLED=true
GIT_REMOTE=origin
BSP_BASE_BRANCH=main
```

When enabled, the agent:

```text
checkout base branch
git pull --ff-only
create bsp-agent/<run_id>
apply approved patch
commit
push bsp-agent/<run_id>
```

It never force-pushes and refuses protected branches such as `main` and `master`.

## GitLab Webhook Trigger

The webhook server receives GitLab Issue Hook events and starts one repair run
against `BSP_REPO_PATH`.

Start the server:

```bash
.venv/bin/bsp-agent serve --host 0.0.0.0 --port 8080
```

Health check:

```bash
curl http://localhost:8080/health
```

Webhook endpoint:

```text
POST /webhook/github
```

The path keeps the old name for compatibility, but the payload is GitLab-only.
Configure GitLab Issue Hook with:

```text
URL:    https://<your-public-url>/webhook/github
Secret: value of GITLAB_WEBHOOK_TOKEN
Event:  Issues events
```

Behavior:

```text
valid issue open event -> 202 and starts background run
duplicate event UUID   -> 200 and does not start another run
invalid token          -> 401
busy active run        -> 409
non-issue/open event   -> 204
```

Webhook runs stop at `human_review`. The agent posts a GitLab issue note only
after human approval and a successful managed publish (`stage == published`).

## Langfuse Observability

Tracing is off unless both keys are set:

```env
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

When enabled:

```text
one trace per run: run:<run_id>
LangGraph nodes appear as spans
LLM calls appear as generations:
  select_skills
  patch_agent
  code_review_agent
```

See:

```text
docs/observability.md
```

## LangGraph Studio

The graph can be exposed to LangGraph local server through:

```text
langgraph.json
agent/studio_graph.py
```

Run:

```bash
.venv/bin/langgraph dev
```

Then open the Studio URL printed by the command.

## Development Checks

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

Current expected status:

```text
70 passed
All checks passed!
```

## More Documentation

```text
spec.md                              product/workflow requirements
docs/system-overview.md              detailed architecture
docs/observability.md                Langfuse setup and tracing design
docs/adr/0002-managed-git-workflow.md
docs/adr/0003-github-webhook-trigger.md
```

`docs/adr/0003-github-webhook-trigger.md` now describes the GitLab webhook design;
the filename is historical.
