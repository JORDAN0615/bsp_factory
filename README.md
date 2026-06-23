# Jetson BSP Repair Agent

Controlled CLI workflow for proposing Jetson BSP source patches, pausing for human review and build/flash handoff, then validating a flashed target device over SSH.

## Setup

```bash
pip install -e .
cp .env.example .env
```

## Basic Flow

```bash
git -C /tmp/bsp-agent-init-camera-smoke-
  repo restore .

bsp-agent init-run \
  --repo /path/to/your/real/bsp-repo \
  --issue "你的實際問題描述" \
  --log /path/to/dmesg.txt

bsp-agent show-diff --run runs/<run_id>
bsp-agent approve --run runs/<run_id>

# Human commits, pushes, builds, and flashes outside the agent.

bsp-agent register-target \
  --run runs/<run_id> \
  --ssh-target nvidia@192.168.1.50 \
  --git-ref abc1234

bsp-agent run-tests --run runs/<run_id> --script camera_check.sh
bsp-agent report --run runs/<run_id>
```

Validation scripts must live in `tests/validation/`.

## LangGraph Boundary

The MVP uses LangGraph internally for the repair pipeline from classification through patch application:

```text
classify_error -> select_skills -> load_skill -> inspect_repo -> propose_patch -> apply_patch
```

Human review is a LangGraph `interrupt` backed by a SQLite checkpointer stored in each run directory:

```text
runs/<run_id>/checkpoints.sqlite
```

The CLI resumes that interrupt through `approve` or `reject`. Target registration, SSH validation, and reporting still use the CLI plus `state.json` artifacts.

## Skill Selection

The agent does not load every skill into the context window. It first builds a metadata catalog from the skill folders, asks the LLM to select at most three relevant skill folders, and only then loads the full selected `SKILL.md` files.

`skills/known_error_patterns.yaml` remains as a fallback when the LLM selector is unavailable or returns invalid JSON.
