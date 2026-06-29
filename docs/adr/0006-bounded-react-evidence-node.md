# Bounded ReAct Evidence Node

Add a bounded, read-only ReAct sub-agent to the repository inspection step.

Status: **Accepted for Phase 1**.

## Context

BSP repair is evidence-driven. A useful patch often depends on following a chain
such as:

```text
dmesg symptom
  -> device-tree node
  -> compatible string
  -> driver file
  -> Kconfig symbol
  -> regulator / clock / reset provider
```

The previous `inspect_repo` implementation used deterministic keyword search and
fixed file reads. That is safe, but weak when the first keyword set is incomplete
or the relevant evidence is discovered only after reading one file.

At the same time, the BSP repair pipeline has safety boundaries that should stay
deterministic:

```text
validate_patch
code_review_agent
human_review
apply_patch
publish
```

The question is where a ReAct agent should live:

1. inside `inspect_repo`, as a read-only evidence researcher; or
2. inside `patch_agent`, where it can research and produce a diff in the same
   loop.

## Decision

Phase 1 puts ReAct **only inside `inspect_repo`**.

The ReAct agent is a bounded read-only evidence gatherer. It may use tools to
search and read the configured BSP repository, then it writes a plain
`repo_inspection.md` (findings plus an investigation trace). It does **not**
produce a diff, does **not** use a fixed-format / structured output, and does not
replace `patch_agent`.

```text
classify_error
  -> select_skills
  -> load_skill
  -> inspect_repo
       if REACT_EVIDENCE_ENABLED=false:
         deterministic keyword repo inspection
       if REACT_EVIDENCE_ENABLED=true:
         bounded ReAct evidence agent
           tools: grep_repo, read_file
           output: repo_inspection.md (findings + investigation trace)
  -> patch_agent              unchanged
  -> validate_patch           unchanged
  -> code_review_agent        unchanged
  -> human_review             unchanged
  -> apply_patch
  -> publish
```

This keeps the responsibility split explicit:

```text
inspect_repo = researcher
patch_agent  = patch writer
```

The agent may explore within `inspect_repo`, but the next node still receives one
distilled `repo_inspection.md` artifact.

## Why Not ReAct in Patch Agent Yet

Putting ReAct directly in `patch_agent` would combine three responsibilities:

```text
1. find evidence
2. choose repair strategy
3. produce unified diff
```

That is more powerful, but harder to debug. If the patch is wrong, it becomes
unclear whether the failure came from bad evidence, bad reasoning, or bad diff
formatting.

Phase 1 intentionally avoids changing:

```text
patch_agent_node
patch_tools.py
diff normalization
code_review_agent
human_review
publish
```

The current patch pipeline remains stable while we measure whether ReAct evidence
gathering improves source localization.

## Implementation Shape

### Feature Flags

```text
REACT_EVIDENCE_ENABLED=false
EVIDENCE_RECURSION_LIMIT=16
```

Default is off. With the flag unset, `inspect_repo` behaves as before.

### Tool Set

Only read-only tools are exposed:

```text
grep_repo(pattern, path=None)
read_file(path, start=None, end=None)
```

Constraints:

```text
repo root is resolved with realpath
paths containing ".." are rejected
absolute paths outside the repo are rejected
symlink escapes are rejected
grep results are capped
read_file output is line-numbered and capped
not-found paths and refused paths return a short "(error: ...)" string,
  the tools never raise into the agent loop
no write / apply / commit / push / shell / ssh tool is registered
```

Read-only is enforced structurally in the tools, not by prompt wording. Tools
returning errors as strings (instead of raising) is what lets the ReAct loop
recover when the model guesses a path that does not exist, and is required to
honor the "does not crash the run" guarantee below.

A `knowledge_search` tool over the BSP knowledge base is a **future** addition
(see ADR-0005, not yet built); Phase 1 exposes only `grep_repo` and `read_file`.

### Agent Factory

Use LangChain's current agent factory:

```python
from langchain.agents import create_agent

agent = create_agent(
    model=model,
    tools=[grep_repo, read_file],
    system_prompt=SYSTEM_PROMPT,
)   # NO response_format — see note below
```

`langgraph.prebuilt.create_react_agent` still exists, but in current LangChain /
LangGraph it is deprecated in favor of `langchain.agents.create_agent`. The new
factory still returns a LangGraph compiled graph internally.

**Verified, no `response_format`.** Binding a `response_format` schema removed the
loop's stop condition on the configured model: the agent kept calling tools and
never produced a final message, hitting the recursion limit (and once overflowing
the model context window). This was reproduced with **both** factories
(`create_react_agent` and `create_agent`). Without `response_format`, the same
model on the same repo converged in ~2 tool calls and produced a final findings
message. Phase 1 therefore takes the plain-text path; any later need for a fixed
schema is done as a separate extraction step through the existing
`chat_completion` choke point, not by binding a schema inside the ReAct loop.

### repo_inspection.md output

Phase 1 has **no structured schema**. The node renders the ReAct run directly into
`repo_inspection.md`, the same artifact the deterministic path already produces and
the only thing `patch_agent` consumes. Two sections:

```text
## Findings
  the agent's final plain-text summary (which dt node / driver / Kconfig is
  implicated, citing the files it actually read)

## Investigation (<k> rounds)
  one bullet per tool call, e.g.
  - grep_repo(pattern="pcie@14180000") -> tegra234-...-pcie.dtsi:1
  - read_file(path="...pcie.dtsi") -> 42 lines
  (each result preview capped; total bullets capped)
```

The `## Findings` section is what guides `patch_agent`; the `## Investigation`
section is for the human / Langfuse to see how many rounds were spent and what was
pulled. There is no diff and no proposed-patch field in Phase 1; the future fixed
patch output format is separate and deferred to Phase 2.

## Incomplete Path

The ReAct loop is bounded by `EVIDENCE_RECURSION_LIMIT`.

If the agent reaches the recursion limit without producing a final message, the
node catches `GraphRecursionError`, renders whatever investigation trace was
collected so far, and appends a note:

```text
## Findings
(investigation did not converge within <N> rounds)

## Investigation (<k> rounds)
... whatever tool calls were made ...
```

It does not raise and does not crash the run. Because tools return error strings
instead of raising (see Tool Set), a wrong path guess can no longer crash the node
either.

Note on bounding: total context consumed by the loop is ultimately bounded by
**convergence**, not by the per-call output caps alone — which is the other reason
`response_format` (which broke convergence) was removed. With it removed the loop
converges in a few rounds and stays well inside the model context window.

## Observability

ReAct internal model/tool calls do not pass through the existing raw
`chat_completion` choke point. When Langfuse is enabled, attach the Langfuse
LangChain `CallbackHandler` to the ReAct agent invoke config so the model and
tool steps appear under the same run trace.

When Langfuse is disabled, no handler is constructed.

## Future Phases

### Phase 2: Evidence Retry Contract

Add a fixed-format output option to `patch_agent`:

```text
DIFF
NO_PATCH
NEED_MORE_EVIDENCE
```

If `patch_agent` returns `NEED_MORE_EVIDENCE`, route back to `inspect_repo` with a
targeted query. `patch_agent` still does not get tools.

### Phase 3: Optional Patch Agent ReAct

Only consider this if Phase 1/2 data shows evidence gathering is still not enough.
At that point, either:

```text
A. keep two ReAct nodes:
   inspect_repo ReAct = broad evidence search
   patch_agent ReAct  = narrow final verification

B. merge ReAct into patch_agent:
   patch_agent ReAct = search + plan + diff
```

Phase 3 would require a stricter structured output contract and additional
observability because it mixes research and patch generation.

## Consequences

Benefits:

```text
adaptive repository evidence gathering
clear separation between evidence and patch generation
patch pipeline remains stable
safe read-only tool boundary
easy fallback to old deterministic inspection
```

Costs:

```text
adds LangChain / langchain-openai dependency for this node
adds a second LLM path besides raw urllib chat_completion
requires Langfuse callback wiring for full ReAct visibility
```

The decision keeps the outer BSP workflow deterministic while allowing one
bounded inner ReAct loop where exploration is useful and safe.
