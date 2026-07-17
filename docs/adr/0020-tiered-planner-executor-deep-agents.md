# Tiered Planner / Executor Deep Agents

Split the single deep agent (ADR-0017) into a **cloud planner** that produces a
structured repair guide and a **local executor** that implements it. The split is a
cost-vs-capability trade, not a separation of concerns: verification showed the
local model alone rarely lands the correct BSP edit, while a frontier cloud model
does — but running everything in the cloud is too expensive.

Status: **Proposed** on branch `feat/deep-agent-integration`. Amends ADR-0017;
independent of the build/validation pipeline (ADR-0018/0019).

## Context

ADR-0016 deliberately unified inspection and editing into one deep agent to avoid a
lossy evidence handoff. This ADR re-introduces two agents, but for a different
reason and with a different seam:

- **Empirical finding.** The local model (`gpt-oss-120b`) can *apply* edits well
  when told precisely what to change (RE-16 showed correct multi-hunk edits; its
  failures were recursion-limit truncation, not wrong edits), but it struggles to
  *decide* the correct fix on a novel BSP problem. Frontier cloud models (Opus,
  GPT-5.x) decide correctly.
- **Cost constraint.** Doing the whole run in the cloud is too expensive. The
  token-heavy part is execution (reading files, iterating edits, retries); the
  high-value reasoning part (localize the fault, choose the fix) is comparatively
  token-light.

So spend expensive cloud tokens only on planning, and cheap local tokens on the
token-heavy mechanical execution. This is a model-cascade: strong-plans /
weak-executes.

Unlike ADR-0016's rejected inspect→patch split, both stages are full deep agents
with read + skill + RAG, so the executor is not blind — the guide is *direction*,
not a compressed evidence dump it must trust.

## Decision

Insert a read-only **planner** deep agent before the existing **executor** deep
agent, gated by `PLANNER_ENABLED` (default off, requires `DEEP_AGENT_ENABLED`):

```text
retrieve_mic741_knowledge
  -> deep_agent_planner   { cloud model · list_skills/load_skill · ls/glob/grep/read_file · preloaded RAG }
       produces -> repair guide (structured)
  -> deep_patch_agent     { local model · + stage_edit_file · consumes the guide }
  -> validate_patch -> code_review_agent -> target_build -> human_review -> ...
```

- **Planner** reuses the ADR-0016/0017 harness but **read-only** (no
  `stage_edit_file`, built-in writes denied, no researcher-write). It discovers
  skills via the tools, reads the repo, and is given the preloaded
  `knowledge_context`. Its sole output is the guide (structured output, validated).
- **Executor** is today's `deep_patch_agent`, unchanged except it now receives the
  guide in its prompt (alongside issue, RAG, retry context) and is explicitly
  pointed at the **local** model.
- With `PLANNER_ENABLED=false`, the executor runs exactly as today (its own
  internal planning), so the split is reversible and A/B-comparable.

### The repair guide contract (the crux)

The guide's precision level decides whether this works. Too vague → the weak
executor must re-plan (the thing it cannot do). Too precise (a full diff) → the
planner did all the work and the executor is pointless. The target is: **say
exactly WHAT and WHERE, leave the HOW (exact text manipulation against real file
content) to the executor.** The executor still reads each file and makes the edit,
so it verifies against reality and catches drift — it just doesn't have to decide
the fix.

Structured schema (validated as the planner's structured output):

```jsonc
{
  "root_cause": "one-paragraph fault localization",
  "strategy": "one-paragraph fix approach",
  "changes": [
    {
      "file": "kernel/hardware/nvidia/t264/.../board.dts",   // repo-relative
      "intent": "what this change achieves",
      "location_hint": "how to find the exact spot: node/symbol/section + a nearby anchor line",
      "edit": "precise change: what to set/add/remove and to what value — NOT a full diff",
      "reference": "optional: MIC-741 case id or skill section this mirrors"
    }
  ],
  "acceptance": ["observable completion checks, e.g. 'all 8 i2c pins present', 'builds clean'"],
  "avoid": ["what not to touch; common mistakes on this subsystem"]
}
```

`location_hint` + `edit` must be specific enough that the executor does not have to
choose the fix, but the executor supplies the exact surrounding text and performs
the `stage_edit_file` calls. `changes` may span multiple files; the executor works
through them and self-verifies against `acceptance`.

### Model configuration

Two model tiers instead of one:

```env
# Executor (unchanged) — local, cheap, token-heavy.
LLM_BASE_URL=http://172.17.5.206:8000/v1
LLM_MODEL=gpt-oss-120b

# Planner — cloud, strong, token-light. Off by default.
PLANNER_ENABLED=false
PLANNER_LLM_BASE_URL=https://api.openai.com/v1     # or an OpenAI-compatible proxy
PLANNER_LLM_API_KEY=...
PLANNER_LLM_MODEL=gpt-5.x
PLANNER_LLM_TIMEOUT_SEC=180
PLANNER_RECURSION_LIMIT=40
```

Provider note: the executor uses `ChatOpenAI`, so an OpenAI-compatible planner
endpoint (GPT-5.x, or Opus behind an OpenAI-compatible proxy) drops in directly.
Native Anthropic Opus would use `langchain_anthropic` — wired only when that model
is actually selected.

### Failure degradation

A transient planner (cloud) failure uses the ADR-0012 ladder: bounded in-node
retries, then pause at `human_review` in `llm_failure` mode. It does **not** fall
back to local-only execution, because local-alone is the proven-weak path — a human
should decide, not silently ship a low-quality attempt.

## Validate before defaulting on

Before flipping `PLANNER_ENABLED` to default-on, measure the three configurations on
the 21 MIC-741 cases (which have ground-truth diffs): all-local, cloud-plan +
local-exec, all-cloud — scoring success rate and token cost. Tune `location_hint`/
`edit` precision to the highest-level guide that keeps success rate flat. The split
is justified only if cloud-plan+local-exec approaches all-cloud success at
near-all-local cost.

## Deferred

- Three-tier (local gathers evidence -> cloud reasons into a guide -> local
  executes) if planner-side file reading proves token-heavy on the cloud.
- Exposing the guide as a human-review checkpoint (approve the plan before code).
- Making MIC-741 retrieval an on-demand tool for the planner (still preloaded; see
  ADR-0017 deferred).

## Consequences

The expensive model is spent only where it changes the outcome (deciding the fix),
and the token-heavy execution stays cheap and local, balancing cost against success
rate. The costs: a second agent loop and added latency; a two-tier model
configuration and cloud dependency/egress; and a new guide contract whose precision
must be tuned empirically. The default-off flag, unchanged downstream gates
(validate/review/build/human), and the 21-case evaluation keep it reversible and
evidence-driven.
