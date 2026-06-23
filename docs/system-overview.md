# Jetson BSP Agent System Overview

This document is the current implementation overview for the Jetson BSP Agent:
architecture, runtime flow, file layout, CLI behavior, artifacts, and current
implementation status.

The product/workflow requirements live in:

```text
spec.md
```

## 1. Goal

The Jetson BSP Agent is a controlled workflow agent for Jetson BSP source repair and validation.

It is not a general-purpose coding agent. Its job is to:

```text
BSP issue / log
  -> classify failure
  -> select relevant Jetson BSP skills
  -> load only selected full skills
  -> inspect the specified BSP source repo
  -> propose a conservative patch
  -> pause for human review
  -> apply approved patch to the working tree
  -> optionally commit/push to bsp-agent/<run_id>
  -> after human build/flash, validate a target device over SSH
  -> produce a report
```

The core safety principle is:

```text
LLM may propose source changes, but dangerous workflow boundaries stay explicit.
```

Commit and push are opt-in (`AUTO_PUSH_ENABLED`, default off) and use a
dedicated per-run branch `bsp-agent/<run_id>`. Build, flash, and SSH/sudo
password handling remain outside the agent.

### Trigger Sources

A repair run always starts from a BSP issue and its logs. The architecture
diagram (`docs/system architecture.png`) shows two ingestion paths feeding the
same run entry point:

```text
Actor (manual)         -> bsp-agent init-run --repo --issue --log   (implemented)
cronjob -> git issue   -> issue / log -> run entry point            (planned)
```

The manual `Actor` path is implemented today. The automated path in the
diagram — a cronjob that polls a git issue tracker on an interval (drawn as
30 minutes) and opens one run per new BSP issue — is a designed ingestion
path and is not yet implemented in the CLI.

## 2. Current Architecture

The current architecture has five layers:

```text
CLI
  -> workflow facade
  -> LangGraph repair graph
  -> deterministic tools
  -> run artifacts / BSP source repo / target device
```

### System Architecture Diagram

```mermaid
flowchart TB
  user[Human Operator]
  cli[bsp-agent CLI<br/>agent/main.py]
  wf[Workflow Facade<br/>agent/nodes/workflow.py]

  subgraph graph[LangGraph Repair Graph<br/>agent/graph.py]
    start((START))
    classify[classify_error]
    select[select_skills<br/>LLM selects skill metadata]
    load[load_skill<br/>load selected full SKILL.md only]
    inspect[inspect_repo<br/>search/read BSP source]
    patchagent[patch_agent<br/>LLM outputs unified diff or NO_PATCH]
    route{patch available?}
    validate[validate_patch<br/>normalize + git apply --check only]
    reviewagent[code_review_agent<br/>independent LLM review, strict JSON]
    nopatch[write_no_patch<br/>auto-retry until budget exhausted]
    review[human_review<br/>LangGraph interrupt]
    decision{resume command}
    apply[apply_patch<br/>apply accepted patch.md]
    publish[publish<br/>optional commit + push]
    end((END))

    start --> classify --> select --> load --> inspect --> patchagent --> route
    route -->|diff| validate
    route -->|NO_PATCH| nopatch
    nopatch -->|retries remain| classify
    nopatch -->|exhausted| end
    validate -->|invalid| nopatch
    validate -->|valid, not applied| reviewagent
    reviewagent -->|reject + retries remain| classify
    reviewagent -->|reject exhausted / needs_human / pass| review
    review --> decision
    decision -->|approve| apply --> publish --> end
    decision -->|reject + feedback| classify
  end

  subgraph tools[Deterministic Tool Layer<br/>agent/tools]
    gittools[git_tools.py<br/>status / diff / clean gate]
    patchtools[patch_tools.py<br/>diff validation / normalize / reverse]
    repotools[repo_tools.py<br/>safe read / rg search]
    skilltools[skill_tools.py<br/>catalog / metadata / load selected skills]
    llmtools[llm_tools.py<br/>chat completion / diff extraction]
    reviewtools[review_tools.py<br/>Code Review Agent prompt / JSON parse]
    testtools[test_tools.py<br/>SSH validation runner]
    artifacts[artifact_tools.py<br/>run files / JSON / reports]
  end

  subgraph external[External Boundaries]
    llm[OpenAI-compatible LLM endpoint]
    skills[skills/&lt;folder&gt;/SKILL.md<br/>NVIDIA Jetson BSP skills]
    repo[(User-specified BSP source repo<br/>working tree is patched directly)]
    target[Flashed Jetson target device<br/>SSH reachable]
    humanbuild[Human-owned steps<br/>build / flash<br/>commit / push if auto-push is off]
  end

  subgraph runfiles[Run Artifacts<br/>runs/&lt;run_id&gt;]
    state[state.json]
    checkpoint[checkpoints.sqlite<br/>LangGraph checkpointer]
    inputs[input.md + raw_logs/]
    attempts[attempts/001...<br/>skill selection / repo inspection / patch / review]
    validation[validation_runs/&lt;n&gt;/result.json<br/>stdout / stderr / exit_code]
    report[report.md]
  end

  user -->|init-run / review / approve / reject| cli --> wf --> graph
  graph --> tools
  select --> llmtools --> llm
  patchagent --> llmtools --> llm
  reviewagent --> reviewtools --> llm
  skilltools --> skills
  repotools --> repo
  gittools --> repo
  patchtools --> repo
  artifacts --> runfiles
  graph --> checkpoint
  wf --> state

  user -->|after approve| humanbuild --> target
  user -->|register-target| cli
  cli -->|run-tests| testtools --> target
  testtools --> validation
  wf --> report
```

### CLI Layer

Implemented in:

```text
agent/main.py
```

Main commands:

```text
bsp-agent init-run
bsp-agent review
bsp-agent approve
bsp-agent reject
bsp-agent show-diff
bsp-agent register-target
bsp-agent run-tests
bsp-agent report
```

`init-run` is interactive by default. When the graph reaches human review, the CLI shows the diff and prompts:

```text
Approve patch? [a=approve, r=reject, q=quit]
```

Use `--no-interactive` for non-interactive smoke tests.

### Workflow Facade

Implemented in:

```text
agent/nodes/workflow.py
```

This file bridges CLI commands and graph/tools. It also contains helper functions for:

```text
input artifact writing
repo inspection text
patch prompt construction
review feedback context
report generation
target registration
validation execution
```

### LangGraph Runtime

Implemented in:

```text
agent/graph.py
```

The repair pipeline uses LangGraph `StateGraph`:

```text
START
  -> classify_error
  -> select_skills
  -> load_skill
  -> inspect_repo
  -> patch_agent
  -> validate_patch | write_no_patch
  -> code_review_agent
      -> classify_error   (reject, retries remain)
      -> human_review     (reject exhausted / needs_human / pass)
  -> human_review
      -> apply_patch      (approve)
      -> classify_error   (reject, retries remain)
      -> END              (reject, retries exhausted -> report)
  -> apply_patch
  -> publish             (no-op unless AUTO_PUSH_ENABLED=true)
  -> END                 (stage target_ready / published / publish_failed)
```

Key properties:

```text
validate_patch runs git apply --check only; nothing is applied during review.
patch.md is written by validate_patch before any review.
apply_patch runs only after human approval.
Rejects never need rollback because nothing was applied.
NO_PATCH and validation failures auto-retry until max_loops, then report.
Code Review Agent reject auto-retries; exhausted rejects escalate to human.
```

`human_review` is a real LangGraph `interrupt`.

Each run creates a durable SQLite checkpointer:

```text
runs/<run_id>/checkpoints.sqlite
```

The graph uses:

```text
thread_id = run_id
```

`approve` and `reject` resume the interrupted graph with `Command(resume=...)`.

### Deterministic Tool Layer

Implemented in:

```text
agent/tools/
```

Tool responsibilities:

```text
artifact_tools.py  -> run IDs, attempt dirs, JSON/text artifact writes
git_tools.py       -> git status, diff, clean source gate, restore
llm_tools.py       -> OpenAI-compatible chat completion, diff extraction
patch_tools.py     -> diff validation, hunk normalization, check/apply, reverse patch
path_tools.py      -> path safety checks
retry_tools.py     -> runtime retry context builder for LLM prompts
review_tools.py    -> Code Review Agent (policy prompt, strict JSON parse, artifacts)
repo_tools.py      -> safe file read/write, rg-based repo search
skill_tools.py     -> skill catalog, metadata parsing, skill loading
test_tools.py      -> SSH upload-and-run validation scripts
```

### State Model

Implemented in:

```text
agent/state.py
```

Important concepts:

```text
BSPAgentState
RepairAttempt
TargetInfo
ValidationRunInfo
```

A run can contain multiple repair attempts. Rejecting a patch creates the next repair attempt. Validation failure can also create another attempt.

## 3. Skill Selection Design

Skills live under:

```text
skills/
```

The current skills are copied from:

```text
/Users/jordan/jetson-bsp-skills/skills
```

This includes real NVIDIA Jetson BSP skills such as:

```text
jetson-customize-camera
jetson-customize-pcie
jetson-customize-pinmux
jetson-customize-usb
jetson-build-source
jetson-validate-image
```

The agent does not load every skill into the context window.

Current flow:

```text
1. Build skill metadata catalog from all skill folders.
2. Send issue, classification, and skill metadata catalog to LLM.
3. LLM selects at most 3 skill folders.
4. Agent validates selected folder names.
5. Agent loads only selected full SKILL.md files.
```

Artifacts:

```text
attempts/<n>/skill_catalog.json
attempts/<n>/skill_selection.json
attempts/<n>/selected_skills.json
attempts/<n>/retrieved_skills.md
```

Fallback:

```text
skills/known_error_patterns.yaml
```

This fallback is used only if LLM skill selection is unavailable, invalid JSON, or selects no valid skills.

## 4. Patch Design

Patch proposal is LLM-driven but apply is deterministic and conservative.

Rules:

```text
LLM must output unified diff or NO_PATCH.
Patch must modify existing files only.
Patch must not create new files.
Patch must pass basic diff validation.
Patch must pass git apply --check.
Patch is applied to the user-specified BSP source working tree.
```

The patch layer currently supports:

```text
fenced diff extraction
plain unified diff
diff --git style
--- / +++ style
hunk header normalization
multiple fenced diff blocks concatenated into one patch
whitespace-relaxed old-block matching (fixes LLM indentation drift)
trimming of invented leading/trailing context lines (still unique-match only)
context padding from the real file (git apply rejects context-free hunks)
trailing newline normalization
changed file summary extraction
reverse patch for reject rollback
```

Whitespace-relaxed matching is still conservative: the old block must match
uniquely after whitespace normalization, context and removed lines are
rewritten to the exact file content, and added lines that duplicate an
existing file line adopt that line verbatim. Ambiguous matches are rejected.

If the LLM output cannot be safely matched to the actual file contents, the agent writes `NO_PATCH` instead of forcing a source edit.

This is intentional. A failed patch apply is safer than changing the wrong BSP file.

## 5. Code Review Agent and Human Review

### Code Review Agent

Implemented in:

```text
agent/tools/review_tools.py
agent/prompts/code_review_policy.md
```

After deterministic validation passes, the Code Review Agent reviews the
validated, not-yet-applied diff. It is a second LLM-backed component with its
own independent context:

```text
issue
selected skills
repo_inspection.md
the proposed diff
BSP review policy (agent/prompts/code_review_policy.md, editable)
retry context from previous attempts
```

It never receives the Patch Agent prompt. Output is strict JSON:

```json
{
  "decision": "pass | reject | needs_human",
  "confidence": 0.9,
  "findings": [],
  "required_changes": []
}
```

Routing:

```text
reject + retries remain  -> findings/required_changes enter retry context,
                            new attempt, back to Patch Agent (no human)
reject + exhausted       -> escalate to human_review (fallback)
needs_human              -> human_review
pass                     -> human_review (human approval always required)
```

Fail-safe: LLM errors or invalid JSON become `needs_human` so a broken
reviewer can never auto-accept or silently burn the retry budget.

Review settings:

```text
CODE_REVIEW_ENABLED=true
```

Artifacts per reviewed attempt:

```text
attempts/<n>/code_review.md
attempts/<n>/review_agent_raw.json
```

### Human Review

Human review remains in MVP as the safety gate and the escalation fallback.
The graph enters `human_review` (a LangGraph interrupt) and the CLI resumes it:

```bash
bsp-agent review --run runs/<run_id>     # shows patch.md + code_review.md
bsp-agent approve --run runs/<run_id>
bsp-agent reject --run runs/<run_id> --feedback "..."
```

Approve:

```text
human_review_status = approved
apply_patch applies the diff from canonical patch.md
publish is a no-op by default, leaving stage = target_ready
if AUTO_PUSH_ENABLED=true, publish commits/pushes to bsp-agent/<run_id>
human builds/flashes outside the agent
```

Reject:

```text
record feedback (no rollback needed; nothing was applied)
create next repair attempt
rerun classify/select/load/inspect/patch_agent/validate/review
```

Reject feedback and review findings are included in the next patch prompt so
the Patch Agent does not repeat the same rejected patch.

## 6. Retry Context

The agent does not use generic long-term memory, vector memory, or standalone
memory files. Each retry instead receives a runtime-built retry context so the
agent does not treat every retry as a fresh first attempt.

### Current Behavior

This is implemented in `agent/tools/retry_tools.py`:

```text
build_retry_context(state) -> str
```

`_propose_patch()` calls it at runtime before every patch proposal and injects
the result into the LLM prompt as
`Retry context (previous attempts in this run):`. No memory files are written;
there is no `attempt_memory.json`, `attempt_memory.md`, or `run_memory.md`.

The retry context is generated from `state.json` data and previous attempts'
artifacts on disk:

```text
previous attempts/*/patch.md          -> bounded patch excerpt
previous attempts/*/no_patch.md       -> no-patch / patch failure reason
attempt.validation_runs stdout/stderr -> bounded output tails
state.json attempt fields             -> skills, changed files, statuses,
                                         human feedback, code review decision,
                                         findings, required changes
```

The compact per-attempt summary includes:

```text
selected skills
changed files
patch status
patch content (bounded excerpt)
human review status
human feedback
validation result with exit code
validation stdout/stderr summary
no-patch or patch failure reason
```

The current in-progress attempt never appears in its own retry context.

Bounded summaries keep the prompt small:

```text
patch excerpt: max 1000 characters
human feedback: max 1000 characters
validation stdout/stderr: tail 10 lines, max 800 characters each
retry context total: max 8000 characters in the prompt
```

The LLM is instructed:

```text
Do not repeat a patch that was rejected by human review.
Use human feedback as higher-priority evidence than your previous patch.
Use validation failures as evidence about runtime behavior on the flashed target.
If the retry context conflicts with skill instructions, explain by returning NO_PATCH.
```

### Prompt Auditing

The actual patch-generation prompt (system and user messages, including the
injected retry context) is saved before every LLM call:

```text
attempts/<n>/proposed_patch_prompt.md
```

This makes the LLM input auditable without separate memory artifacts. It is
written even when the LLM call fails, so failed attempts are debuggable.

## 7. Publish / Build / Flash

After approve, the agent applies the accepted patch. Commit/push is opt-in.

Default behavior:

```text
git add / commit / push
build BSP
flash Jetson target device
```

When enabled:

```text
AUTO_PUSH_ENABLED=true
GIT_REMOTE=origin
```

the agent commits and pushes the applied patch to:

```text
bsp-agent/<run_id>
```

This is an implementation of `docs/adr/0002-agent-push-after-approval.md`.
The agent never force-pushes and refuses protected branches such as `main` and
`master`.

Human-owned steps always remain:

```text
build BSP
flash Jetson target device
```

The agent resumes after the target device is ready.

Register target:

```bash
bsp-agent register-target \
  --run runs/<run_id> \
  --ssh-target nvidia@192.168.1.50 \
  --git-ref <human-declared-git-ref>
```

`git-ref` is recorded as human-declared evidence. MVP does not verify it on the target device.

## 8. Validation Design

Validation scripts live under:

```text
tests/validation/
```

The agent only runs scripts from that allowlisted folder.

Execution mode:

```text
upload script to target under /tmp/bsp-agent/<run_id>/...
run uploaded copy through SSH
save stdout, stderr, exit code, duration
```

Pass/fail rule:

```text
exit code 0     -> success
exit code != 0  -> failed
```

The LLM may analyze failure logs, but it cannot override the exit code.

## 9. Run Artifact Layout

Each run creates:

```text
runs/<run_id>/
  state.json
  input.md
  checkpoints.sqlite
  raw_logs/
  attempts/
    001/
      selected_skills.json
      repo_inspection.md
      proposed_patch_prompt.md
      proposed_patch_raw.md
      patch.md
      code_review.md
      review_agent_raw.json
      no_patch.md
      review.md
      target.json
      validation_runs/
        001_<script>/
          result.json
          stdout.txt
          stderr.txt
      debug/
        error_classification.json
        skill_catalog.json
        skill_selection.json
        retrieved_skills.md
  report.md
```

Not every artifact exists in every attempt. For example, a no-patch attempt has `no_patch.md` but no `patch.md`.

`patch.md` is the canonical patch artifact, written by `validate_patch` before
any review. It contains the attempt number, the changed files, and one fenced
diff block with the full unified diff. `apply_patch` extracts the diff from
`patch.md` when the patch is accepted. There is no separate `patch.diff`,
`patch_summary.md`, or `changed_files.json`.

## 10. Main File Map

Project metadata:

```text
pyproject.toml
.env.example
README.md
spec.md
CONTEXT.md
docs/adr/0001-direct-working-tree-for-mvp.md
docs/system-overview.md
```

Agent source:

```text
agent/main.py              CLI entrypoint
agent/config.py            env/config model
agent/state.py             Pydantic run state
agent/graph.py             LangGraph graph, interrupt, SQLite checkpointer
agent/nodes/workflow.py    CLI workflow facade and helper functions
agent/tools/*.py           deterministic tools
```

Skills:

```text
skills/<jetson-skill-folder>/SKILL.md
skills/<jetson-skill-folder>/skill-card.md
skills/known_error_patterns.yaml
```

Tests and fixtures:

```text
tests/test_*               unit and smoke tests
tests/fixtures/            sample dmesg logs
tests/validation/          allowlisted validation scripts
```

Temporary test BSP repo:

```text
/tmp/bsp-agent-test-repo
```

This repo currently contains camera-oriented BSP fixture files:

```text
arch/arm64/boot/dts/nvidia/tegra234-p3767-camera-imx219.dtsi
arch/arm64/boot/dts/nvidia/tegra234-p3767-regulators.dtsi
arch/arm64/boot/dts/nvidia/tegra234-p3767-camera-overlay.dts
arch/arm64/configs/p3767_camera_defconfig
drivers/media/i2c/imx219_board_check.c
```

## 11. Current CLI Usage

Run camera repair test:

```bash
cd /Users/jordan/bsp-agent

.venv/bin/bsp-agent init-run \
  --repo /tmp/bsp-agent-test-repo \
  --issue "After flashing custom Orin NX BSP, imx219 camera probe fails with i2c -121 and missing camera regulator" \
  --log tests/fixtures/sample_dmesg_imx219_regulator_fail.txt
```

Non-interactive mode:

```bash
.venv/bin/bsp-agent init-run --no-interactive \
  --repo /tmp/bsp-agent-test-repo \
  --issue "After flashing custom Orin NX BSP, imx219 camera probe fails with i2c -121 and missing camera regulator" \
  --log tests/fixtures/sample_dmesg_imx219_regulator_fail.txt
```

Inspect skill selection:

```bash
cat runs/<run_id>/attempts/001/skill_selection.json
cat runs/<run_id>/attempts/001/selected_skills.json
sed -n '1,220p' runs/<run_id>/attempts/001/retrieved_skills.md
```

Review pending patch:

```bash
.venv/bin/bsp-agent review --run runs/<run_id>
```

Show diff:

```bash
.venv/bin/bsp-agent show-diff --run runs/<run_id>
```

Approve:

```bash
.venv/bin/bsp-agent approve --run runs/<run_id>
```

Reject:

```bash
.venv/bin/bsp-agent reject \
  --run runs/<run_id> \
  --feedback "Use board-specific DTS only"
```

Register target:

```bash
.venv/bin/bsp-agent register-target \
  --run runs/<run_id> \
  --ssh-target nvidia@192.168.1.50 \
  --git-ref <commit-or-branch>
```

Run validation:

```bash
.venv/bin/bsp-agent run-tests \
  --run runs/<run_id> \
  --script boot_check.sh
```

Generate report:

```bash
.venv/bin/bsp-agent report --run runs/<run_id>
```

## 12. Verification Commands

Run tests:

```bash
cd /Users/jordan/bsp-agent
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Expected current result:

```text
pytest: 42 passed
ruff: All checks passed
```

## 13. Current Status

Implemented:

```text
Typer CLI
LangGraph StateGraph repair pipeline
LangGraph interrupt for human review
SQLite checkpointer per run
LLM skill selection using metadata catalog
on-demand full SKILL.md loading
real NVIDIA Jetson BSP skills copied into skills/
clean source gate
validate-before-apply (review happens on unapplied diff; repo stays clean)
diff parsing / validation / hunk normalization
Code Review Agent (independent context, strict JSON, policy file)
auto-retry on NO_PATCH / validation failure / review reject
exhausted review rejects escalate to human review
apply on acceptance from canonical patch.md
target registration
SSH upload-and-run validation scripts
runtime retry context (incl. review findings) injected into patch prompts
proposed_patch_prompt.md prompt auditing
debug artifacts under attempts/<n>/debug/
report generation
unit and smoke tests
```

Current known limitation:

```text
LLM-generated patches can still fail if the old hunk content (ignoring whitespace) does not match the real file, or matches ambiguously.
```

Hunk normalization now tolerates whitespace drift (the 2026-06-12 camera test
failure where the LLM re-indented a full DTS node) and pads missing context
lines from the real file so `git apply` accepts context-free full-block
replacements. Remaining mismatches still result in `NO_PATCH`, which is safe.

Recommended next improvements:

```text
1. Add a patch-repair node that asks LLM to fix invalid diffs using git apply errors.
2. Add line-numbered source excerpts to repo_inspection.md.
3. Prefer small targeted edits generated by structured operations before converting to diff.
4. Add sync-skills command to update skills/ from upstream NVIDIA repo.
```

## 14. Design Decisions

Direct working tree:

```text
The MVP modifies the user-specified BSP source working tree directly.
The repo must be clean before init-run.
Commit/push is opt-in and goes to bsp-agent/<run_id>.
```

Recorded in:

```text
docs/adr/0001-direct-working-tree-for-mvp.md
```

Human build/flash handoff:

```text
The agent stops after approval when auto-push is off.
With auto-push on, the agent commits/pushes after approval.
Human owns build/flash.
Agent resumes only after register-target.
```

Skill loading:

```text
Only metadata is loaded first.
LLM chooses skills.
Only selected full skill files are loaded.
Regex routing is fallback only.
```

Validation:

```text
Validation script exit code is authoritative.
LLM analysis cannot override pass/fail.
```
