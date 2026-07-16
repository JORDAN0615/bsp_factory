# Deep Agent Patch Stage

Use LangChain Deep Agents as an experimental replacement for the repository
inspection and agentic patch-generation segment of the BSP repair graph. Keep the
deterministic workflow and all approval boundaries around it.

Status: **Experimental**, implemented behind `DEEP_AGENT_ENABLED=false` on branch
`feat/deep-agent-integration`.

## Context

The current pipeline separates repository exploration from editing:

```text
load_skill -> retrieve_mic741_knowledge -> inspect_repo -> patch_agent
```

ADR-0006 gave `inspect_repo` a bounded ReAct loop, and ADR-0011 gave
`patch_agent` another read/edit ReAct loop over a staging worktree. This is safe,
but it duplicates agent loops and forces the first loop to summarize evidence for
the second. The patch actor may need to rediscover context, while large evidence
artifacts are manually truncated and assembled.

Deep Agents is a LangGraph-based agent harness with built-in planning, filesystem
navigation, context summarization/offloading, and subagent delegation. It fits the
open-ended investigation-and-editing segment, but it is not a replacement for the
deterministic BSP lifecycle.

## Decision

Add an alternative `deep_patch_agent` node after selected skills and MIC-741
knowledge have been loaded:

```text
classify_error
  -> select_skills
  -> load_skill
  -> retrieve_mic741_knowledge
       | DEEP_AGENT_ENABLED=false -> inspect_repo -> patch_agent
       | DEEP_AGENT_ENABLED=true  -> deep_patch_agent
  -> validate_patch
  -> code_review_agent
  -> human_review
  -> apply_patch
  -> publish
```

The Deep Agent owns one bounded loop containing planning, repository search,
reading, optional read-only delegation, staging edits, and post-edit verification.
Its only output to the outer graph is the staging worktree's real `git diff` (or
`NO_PATCH`).

### What it replaces

When enabled, it replaces:

- deterministic or ReAct `inspect_repo` execution;
- the single-shot or LangChain `patch_agent` execution;
- the explicit `repo_inspection.md` handoff between those two actors.

It consumes the already selected full skill text and retrieved MIC-741 matches.
Phase 1 deliberately keeps `select_skills`, `load_skill`, and knowledge retrieval
outside the harness so retrieval behavior remains measurable and reversible.

### What it does not replace

The following remain outer LangGraph nodes and cannot be bypassed:

- deterministic patch validation;
- independent Code Review Agent;
- human-review interrupt and explicit approval;
- applying the accepted diff to the real BSP working tree;
- commit/push, build/flash, target validation, and reporting.

Deep Agents' own tool-call interrupts are not used as the patch-approval gate. A
tool-call approval would approve an individual staging edit, while this system
requires review of the complete generated diff before anything reaches the real
working tree.

## Execution and safety model

- Each invocation receives a detached git staging worktree at the current run
  base. The staging directory is always removed in `finally`.
- A `FilesystemBackend` is rooted at the staging directory with virtual path
  normalization.
- Built-in filesystem writes are denied. The only write capability is
  `stage_edit_file`, an exact string replacement tool structurally scoped by the
  existing `editable_repo` context to existing files in staging.
- There is no shell, new-file creation, delete, commit, push, build, or flash tool.
- The delegated `general-purpose` subagent is read-only and does not inherit
  `stage_edit_file`.
- Transient model failures use ADR-0012's bounded in-node retry and human failure
  pause without consuming a Repair Attempt.
- A recursion-limit stop may retain partial staging edits, but they still pass
  deterministic validation, independent code review, and human review.

## Version choice

Pin `deepagents>=0.6.12,<0.7`, the current stable line. The current documentation
shows a filesystem tool allowlist that requires the `0.7` alpha line. This design
does not depend on that alpha API: stable filesystem permissions deny built-in
writes, and a custom staging-only edit tool provides the narrow mutation surface.

## Configuration

```env
DEEP_AGENT_ENABLED=false
DEEP_AGENT_RECURSION_LIMIT=60
```

The default is off, preserving the current pipeline exactly. `PATCH_AGENT_AGENTIC`
and `REACT_EVIDENCE_ENABLED` are ignored only when the Deep Agent path is selected;
they remain valid for the legacy path.

## Deferred

- Let Deep Agents progressively discover `skills/` itself and retire the external
  `select_skills` / `load_skill` pair after selection quality is measured.
- Expose the MIC-741 query as an on-demand tool instead of only preloading top-K
  context, so the agent can reformulate retrieval during debugging.
- Add a sandbox backend with a narrowly allowlisted test runner. Host shell access
  is intentionally excluded from this phase.
- Evaluate whether multiple specialized read-only subagents improve BSP repair
  quality enough to justify their latency and token cost.

## Consequences

The patch actor can now gather additional evidence whenever needed instead of being
limited to one inspection summary. The cost is a heavier and less deterministic
inner loop, more model calls, and dependence on Deep Agents' evolving harness API.
The default-off flag, stable-version pin, staging boundary, and unchanged outer
gates make the experiment reversible and safe to compare with the existing path.
