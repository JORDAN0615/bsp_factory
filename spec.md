# Jetson BSP Agent Spec

This document defines the target behavior for the Jetson BSP Agent.

For current implementation details, file map, CLI behavior, and known status,
see:

```text
docs/system-overview.md
```

## 1. Goal

Build a Jetson BSP repair and validation workflow agent.

The agent is not a general coding assistant. It owns a controlled BSP workflow:

```text
issue/log
  -> select relevant Jetson BSP skills
  -> inspect the specified BSP source repo
  -> Patch Agent proposes a patch
  -> deterministic patch validation
  -> Code Review Agent reviews the patch
  -> human review if required
  -> human commit / push / build / flash
  -> agent validates flashed target over SSH
  -> failed validation returns to patch generation
  -> successful validation generates report
```

The final direction is to reduce or remove human review. The MVP keeps human
review as a safety gate while the Code Review Agent is introduced and evaluated.

## 2. Architecture

There is one product-level agent:

```text
Jetson BSP Agent
```

Inside it, LangGraph orchestrates deterministic steps and LLM-backed agents:

```text
LangGraph workflow
  -> deterministic steps
  -> Patch Agent
  -> Code Review Agent
  -> optional human review interrupt
  -> validation / retry / report
```

Terminology:

```text
Patch Agent
  LLM-backed component that generates a unified diff or NO_PATCH.

Code Review Agent
  LLM-backed component with a separate review context. It decides whether the
  proposed patch is acceptable, should be rejected, or needs human review.

Skill selection
  A workflow step, not a separate agent. It selects relevant skills before patch
  generation.

Validation retry
  A workflow behavior, not a separate agent. Validation errors are added to retry
  context and sent back to the Patch Agent.
```

Agents do not call each other directly. They communicate through graph state and
artifacts. LangGraph controls routing.

## 3. Non-Goals

Out of scope for the current design:

```text
automatic BSP build
automatic device flashing
storing SSH or sudo passwords
cross-run vector memory
general-purpose repo refactoring
letting LLM override patch validation
letting LLM override validation exit code
```

For now, automatic commit/push is also out of scope. Human commit/push can be
added later after review confidence is proven.

## 4. Human / Agent Boundary

The agent may:

```text
read issue and logs
select relevant skills
inspect the specified local BSP repo
generate patch proposals
validate patches deterministically
run AI code review
apply accepted patches to a clean local working tree
rollback rejected patches
run allowlisted validation scripts over SSH
record artifacts
generate reports
```

The human currently owns:

```text
final patch approval when required
git add / commit / push
BSP build
device flashing
declaring which git ref was flashed
```

Long-term target:

```text
Code Review Agent can replace human review for high-confidence safe patches.
Human review remains the fallback for uncertain or risky patches.
```

## 5. Required Workflow

### 5.1 Intake

Input:

```text
repo path
issue text
optional log files
```

Requirements:

```text
repo must be a git repo
repo must be clean before init-run
run artifacts must be created under runs/<run_id>/
input logs must be copied into the run directory
```

### 5.2 Skill Selection

The agent must not load every full skill into the LLM context.

Required behavior:

```text
build metadata catalog from skills/
send issue + classification + metadata catalog to LLM
LLM selects at most N skill folders
agent validates selected folder names
agent loads only selected full SKILL.md files
fallback to known_error_patterns.yaml if LLM selection fails
```

This remains a workflow step, not a separate agent.

### 5.3 Repo Inspection

The agent should inspect only the user-specified BSP source repo.

Required behavior:

```text
derive search keywords from issue, logs, classification, and selected skills
search repo using safe fixed-string search
read bounded excerpts from candidate files
save repo_inspection.md
```

`repo_inspection.md` is required evidence. It records which source files and
excerpts the Patch Agent and Code Review Agent can rely on.

### 5.4 Patch Agent

The Patch Agent is the LLM-backed patch-generation component.

Input context:

```text
issue
logs / classification
selected skills
loaded skill text
repo_inspection.md
retry context from previous attempts
human or Code Review Agent feedback from previous attempts
validation failure output from previous attempts
```

Output:

```text
unified diff
or NO_PATCH with reason
```

Requirements:

```text
output only a git-apply-compatible unified diff or NO_PATCH
modify existing files only
do not invent board facts not present in repo inspection or skills
prefer minimal patches
save proposed_patch_prompt.md
save proposed_patch_raw.md
```

### 5.5 Deterministic Patch Validation

Before any patch is applied:

```text
validate diff format
validate files are under repo
validate patch modifies existing files only
normalize safe hunks if possible
run git apply --check
```

If validation fails:

```text
write no_patch.md or patch-validation failure artifact
do not apply patch
route back to Patch Agent if retry budget remains
otherwise require human review or report failure
```

### 5.6 Code Review Agent

The Code Review Agent is a separate LLM-backed reviewer. It has its own prompt,
context, goal, and output schema.

It reviews the proposed patch before final acceptance.

Input context:

```text
issue
selected_skills.json
repo_inspection.md
proposed patch diff
BSP review policy
retry context from previous rejected patches
validation failure context when available
```

It should not receive the full Patch Agent prompt as its main context. It should
review the patch independently using evidence and policy.

Output must be strict JSON:

```json
{
  "decision": "pass",
  "confidence": 0.9,
  "findings": [],
  "required_changes": [],
  "human_required": false
}
```

Allowed decisions:

```text
pass
reject
needs_human
```

Review rules:

```text
reject invalid DTS/property names
reject invented regulators, clocks, GPIOs, or board facts
reject patches that modify unrelated files
reject patches not supported by repo_inspection.md
reject patches that repeat previous rejected changes
needs_human for board-specific uncertainty
pass only when the patch is minimal, supported by evidence, and safe enough
```

Routing:

```text
decision = reject
  -> do not apply patch
  -> feed required_changes back into retry context
  -> create next attempt
  -> return to Patch Agent

decision = needs_human
  -> go to human_review

decision = pass and confidence >= auto_approve_threshold
  -> apply patch
  -> if auto approval disabled, still go to human_review
  -> if auto approval enabled, go to target_ready
```

MVP setting:

```text
auto approval disabled
Code Review Agent pass still goes to human_review
Code Review Agent reject automatically retries
```

Future setting:

```text
auto approval enabled for high-confidence pass
human review only for needs_human or low-confidence pass
```

### 5.7 Human Review

Human review remains in MVP.

Required behavior:

```text
show patch.md
support approve
support reject with feedback
reject must rollback applied patch if already applied
reject must create next attempt
reject feedback must be available to the next Patch Agent prompt
```

If Code Review Agent is enabled, human review should receive:

```text
patch.md
code_review.md
review_agent_raw.json
```

### 5.8 Human Build / Flash Handoff

After approval:

```text
agent stops at target_ready
human commits / pushes / builds / flashes outside the agent
human registers the flashed target when ready
```

The MVP records `git-ref` as human-declared evidence. It does not verify that
the target actually contains the ref.

### 5.9 Validation

Validation scripts must come from:

```text
tests/validation/
```

Required behavior:

```text
upload selected script to target over SSH
execute uploaded script on target
record stdout, stderr, exit code, and duration
exit code 0 means success
exit code non-zero means failed
LLM cannot override exit-code based status
```

If validation fails and retry budget remains:

```text
add validation result to retry context
create next repair attempt
return to Patch Agent
```

If validation succeeds:

```text
generate report.md
```

## 6. LangGraph Shape

Target graph:

```text
START
  -> classify_error
  -> select_skills
  -> load_skill
  -> inspect_repo
  -> patch_agent
  -> validate_patch
  -> code_review_agent
  -> route_after_code_review
      -> patch_agent        when rejected and retries remain
      -> human_review       when needs_human or auto approval disabled
      -> apply_patch        when pass and auto approval enabled
  -> human_review
      -> patch_agent        when human rejects and retries remain
      -> target_ready       when human approves
  -> register_target
  -> run_tests
      -> patch_agent        when validation fails and retries remain
      -> report             when validation passes or retries exhausted
  -> END
```

MVP may keep `apply_patch` before human review if that is simpler, but the
preferred design is:

```text
propose diff
validate diff without applying
review diff
apply only after accepted by Code Review Agent and/or human review
```

## 7. Retry Context

Do not create standalone memory files.

Required behavior:

```text
do not create attempt_memory.json
do not create attempt_memory.md
do not create run_memory.md
build retry context at runtime from existing artifacts and state.json
inject retry context into Patch Agent prompt
current in-progress attempt must not appear in its own retry context
```

Retry context should be generated from:

```text
state.json
previous attempts/*/patch.md
previous attempts/*/review.md
previous attempts/*/code_review.md
previous attempts/*/review_agent_raw.json
previous attempts/*/no_patch.md
previous attempts/*/validation_runs/*/result.json
previous attempts/*/validation_runs/*/stdout.txt
previous attempts/*/validation_runs/*/stderr.txt
```

The generated retry context should include compact summaries of:

```text
selected skills
changed files
patch status
Code Review Agent decision and findings
human review status
human feedback
validation result
validation stdout/stderr summary
no-patch or patch failure reason
```

The generated Patch Agent prompt should be saved as:

```text
proposed_patch_prompt.md
```

## 8. Artifacts

Each run should contain:

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

Required root attempt artifacts:

```text
selected_skills.json
repo_inspection.md
proposed_patch_prompt.md
proposed_patch_raw.md
patch.md or no_patch.md
code_review.md when Code Review Agent runs
review_agent_raw.json when Code Review Agent runs
review.md when human review runs
validation_runs/ when validation runs
```

Debug artifacts should go under:

```text
attempts/<n>/debug/
```

`patch.md` is the canonical patch artifact. It should include:

```text
attempt number
changed files
one fenced diff block containing the full unified diff
```

There should be no separate:

```text
patch.diff
patch_summary.md
changed_files.json
attempt_memory.json
attempt_memory.md
run_memory.md
```

## 9. CLI Requirements

Required commands:

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

Useful development scripts:

```text
scripts/verify.sh
scripts/init-camera-smoke.sh
```

`init-camera-smoke.sh` should create a disposable clean BSP fixture repo and
run `init-run` against it.

## 10. Acceptance Criteria

The system is acceptable when:

```text
init-run creates a durable run
skill selection uses metadata before loading full skills
Patch Agent prompt is saved
Patch Agent raw response is saved
patches are validated before apply
patch.md is the canonical patch artifact
Code Review Agent emits strict JSON decision
Code Review Agent reject causes a new patch attempt
Code Review Agent pass reaches human review in MVP
human review uses an interrupt/checkpoint boundary
human reject feedback causes a new attempt
validation failure causes a new attempt when retries remain
validation success generates report.md
retry context from previous attempts is injected into Patch Agent prompts
all important decisions are written as artifacts
```

## 11. Implementation Priority

Implement in this order:

```text
1. Align artifacts with patch.md and debug/ layout.
2. Ensure retry context is runtime-generated from existing artifacts.
3. Add Code Review Agent prompt, parser, and artifacts.
4. Add LangGraph route after Code Review Agent.
5. Keep human review after Code Review Agent pass.
6. Add auto approval only after review quality is proven.
```
