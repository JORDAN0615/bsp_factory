# Deep Agent as Core: Native Skill Discovery

Promote the Deep Agent (ADR-0016) from an experimental patch stage to the **core**
repair actor, and move skill discovery/loading *inside* the harness via Deep Agents'
native `skills` feature. This is the first split-out of the original oversized
ADR-0017; the build, validation, and device-deploy pipeline moved to
ADR-0018/0019/0020/0021.

Status: **Proposed** on branch `feat/deep-agent-integration`. Promotes ADR-0016's
default-off deep-agent path toward the primary flow.

## Scope of this ADR (deliberately narrow)

In: make the deep agent the core actor; let it discover and read Jetson skills via
the native `skills` middleware so it decides which skill it needs; keep its existing
read (`ls` / `glob` / `grep` / `read_file`) and edit (`stage_edit_file`) capability.

**Out (explicitly deferred):**

- **MIC-741 RAG is not a tool in this ADR.** It stays exactly as today — an
  external preloaded `knowledge_context` fed into the deep agent's prompt by the
  `retrieve_mic741_knowledge` node (ADR-0013/0014/0015, unchanged). Turning
  retrieval into an on-demand `search_mic741_knowledge` tool is a later,
  independent decision.
- Build / validation / device pipeline — ADR-0018 onward.

## Context

ADR-0016 added `deep_patch_agent` behind `DEEP_AGENT_ENABLED=false`, replacing only
`inspect_repo` + `patch_agent`. It kept `select_skills` and `load_skill` as external
deterministic nodes that pick and preload skill text before the agent runs. On a
novel problem the agent cannot pull a *different* skill mid-investigation — it is
locked to whatever the upfront selector chose. Skill discovery is exactly the kind
of open-ended, evidence-driven choice the deep agent is built to make.

MIC-741 retrieval has the same shape in principle, but the RAG pipeline is newly
built and its preload behavior is measurable and stable; per this ADR's scope it is
left untouched so only one variable changes here.

## Decision

### 1. The deep agent becomes the core path

Make the deep-agent path the recommended default (`DEEP_AGENT_ENABLED=true`). The
legacy `inspect_repo → patch_agent` path and its `select_skills` / `load_skill`
nodes remain wired for `DEEP_AGENT_ENABLED=false`, so the change stays reversible
and A/B-comparable.

### 2. Skill discovery via the native deepagents `skills` feature

Use Deep Agents' built-in `skills` mechanism (progressive disclosure via
`SkillsMiddleware`): skill *metadata* is injected into the agent's context up front,
and the agent reads a skill's full `SKILL.md` on demand with `read_file`. Our
`skills/*/SKILL.md` already carry the `name`/`description` frontmatter the middleware
expects.

Because the middleware reads skills through the agent's filesystem backend (the
staging worktree), and our skills live in the orchestrator outside that root, the
executor **mounts** `skills/` into the backend root as an untracked `.deep-skills/`
directory before running (`mount_skills`). `git diff` reports only tracked changes,
so the mounted copy never leaks into the generated patch (verified).

The agent discovers the right skill when its investigation tells it which subsystem
it is in (pinmux, camera, can, mgbe, …), instead of receiving a fixed pre-selected
blob. On the deep path this **retires the `select_skills` and `load_skill` nodes**.
(Trade-off: native loading has no hook, so the per-attempt `selected_skills` record
that the earlier custom `load_skill` tool populated is no longer tracked.)

The agent keeps everything else from ADR-0016 verbatim: the `ls`/`glob`/`grep`/
`read_file` read tools, the single `stage_edit_file` mutation tool (exact string
replacement on existing files only — no create/delete/shell), the read-only
`general-purpose` researcher subagent, the detached staging worktree, denied
built-in writes, and the ADR-0012 transient-failure degradation via
`_run_staging_agent`.

```text
issue (intake + classify)
  -> deep_patch_agent {
       plan · ls/glob/grep/read_file · native skills (SkillsMiddleware) · stage_edit_file · verify
     }
  -> validate_patch -> code_review_agent -> human_review -> apply_patch -> publish
```

`retrieve_mic741_knowledge` still runs before `deep_patch_agent` and still feeds
`knowledge_context` into the prompt — unchanged.

## What it replaces / does not replace

Replaces (deep path only): the external `select_skills` / `load_skill` nodes, now
tools the agent drives itself.

Does **not** touch: MIC-741 retrieval (still preloaded), `validate_patch`, the
independent `code_review_agent`, the human-review interrupt, `apply_patch`, and
`publish`. Every approval boundary is exactly as today. Deep Agents' own tool-call
interrupts are still not used as an approval gate — the human reviews the complete
generated diff.

## Configuration

```env
DEEP_AGENT_ENABLED=true          # deep agent is now the primary path
DEEP_AGENT_RECURSION_LIMIT=60
```

With `DEEP_AGENT_ENABLED=false` the legacy path (including `select_skills` /
`load_skill`) is unchanged. `PATCH_AGENT_AGENTIC` / `REACT_EVIDENCE_ENABLED` remain
valid only on the legacy path.

## Deferred

- `search_mic741_knowledge` as an on-demand retrieval tool (let the agent
  reformulate queries mid-debug instead of living with one preloaded top-K blob).
- Retiring `select_skills` / `load_skill` on the legacy path too, once the
  tool-driven selection quality is measured against the current selector.

## Consequences

The agent gains agency over which skill it reads, chosen from evidence rather than
an upfront guess, which better fits novel problems that do not map cleanly to one
pre-selected skill. The cost is a less deterministic skill-selection step and more
model calls inside the loop. Scope is kept to one change (skill), leaving RAG and
the build pipeline for their own ADRs; the default-comparison flag and unchanged
approval gates keep it reversible.
