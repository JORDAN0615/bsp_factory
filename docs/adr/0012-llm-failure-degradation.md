# LLM Failure Degradation and Retry Ladder

Transient LLM-provider failures (request timeouts, connection errors, rate
limits, 5xx) must never crash a repair run, leak the webhook run lock, or
consume the `max_loops` budget that exists for *patch-quality* retries. They are
handled by a three-layer ladder: (1) a larger, configurable request timeout with
SDK-level retries, (2) one delayed in-node retry, and (3) a `human_review` pause
in a new `llm_failure` mode where a human presses Retry or Abandon.

Status: **Proposed**.

## Context

### The incident

A run crashed with `openai.APITimeoutError` raised from inside the agentic
patch agent. The exception escaped `graph.invoke()` and killed the run
mid-pipeline. The request had *reached* the LLM server; it simply did not
complete within the hardcoded 60-second timeout. With a self-hosted model and
the patch agent's large prompt (up to 40k inspection + 20k skills), 60 seconds
is routinely exceeded by *legitimate* generation, not only by outages.

### Why only the agentic nodes crash

`agent/tools/llm_tools.py` is documented as the single LLM choke point: it
raises `LLMError`, and every caller degrades gracefully:

| Call site | Channel | Transient-failure handling |
|---|---|---|
| `_select_skills_with_llm` | `chat_completion` (urllib) | `LLMError` -> deterministic skill fallback |
| `_propose_patch` (non-agentic) | `chat_completion` | `LLMError` -> no-patch reason |
| `run_code_review` | `chat_completion` | `LLMError` -> `needs_human` (fail-closed) |
| `gather_evidence` (ADR-0006) | `ChatOpenAI` (langchain) | **none** — only `GraphRecursionError` |
| `run_patch_agent` (ADR-0011) | `ChatOpenAI` | **none** — only `GraphRecursionError` |

The two agentic nodes bypass the choke point. `ChatOpenAI` raises `openai.*`
exceptions, not `LLMError`, so nothing catches them and the whole graph
invocation fails.

### Blast radius of an escaped exception

1. **Zombie run.** `state.json` is left at a non-terminal stage
   (`inspect_repo` / `propose_patch`). The run is invisible to
   `list_pending_runs`, produces no report, and posts nothing to GitLab.
2. **Webhook lock leak (worst).** For a webhook run paused at `human_review`, a
   console *reject* re-enters the pipeline synchronously. If the retry then
   times out, `api_reject_run` only catches `(RuntimeError, ValueError)`, so
   the endpoint returns 500 and `run_lock` is never released — every later
   webhook issue gets 409 until a human clears the lock by hand.
3. **Managed-branch leak.** With `AUTO_PUSH_ENABLED`, the repo is left checked
   out on `bsp-agent/<run_id>`; `_cleanup_managed_branch` only runs on the
   normal report path.

### The budget conflation

Routing a timeout through the existing no-patch path would call
`new_attempt()` and burn one `max_loops` slot per timeout:

```text
max_loops budget:   "the model's patch was not good enough, try again with
                     feedback"                          — quality retries
timeout reality:    "the LLM server was slow or briefly unavailable; the same
                     context will succeed later"        — transport retries
```

An LLM outage of a few minutes would burn the whole budget and end the run at
`report` (or strand a human-directed run at `human_review` with nothing to
approve). Transport failures must not consume quality-retry budget.

## Decision

### Failure classification

`llm_tools.py` exports the transient-error set used everywhere:

```python
LLMError                       # urllib choke point
openai.APITimeoutError         # reached server, no response in time
openai.APIConnectionError      # could not reach server
openai.RateLimitError          # 429
openai.InternalServerError     # 5xx
```

The `openai` import is guarded (it is already an installed dependency of
`langchain-openai`; no new dependency is added). Non-transient exceptions
(auth errors, programming errors) are out of scope here and still propagate.

### Layer 1 — request level (automatic, seconds)

New settings, threaded through **all five** call sites:

```env
LLM_TIMEOUT_SEC=180        # was hardcoded 60
LLM_MAX_RETRIES=2          # ChatOpenAI/openai SDK retry with backoff
```

180 s absorbs the "large prompt legitimately generates for >60 s" class — the
actual root cause of the observed incident. The urllib `chat_completion` path
gets the timeout only (its callers already degrade; it needs no retry loop).

### Layer 2 — node level (automatic, minutes)

`patch_agent_node` retries the whole staging cycle on transient failure:

```text
create staging worktree -> run_patch_agent
  transient failure:
    save partial diff to attempts/<n>/debug/partial_patch_round<i>.diff
    remove staging worktree (discard partial edits — Conservative Patch)
    if node retries remain: sleep LLM_FAILURE_RETRY_DELAY_SEC, re-run
```

```env
LLM_FAILURE_NODE_RETRIES=1
LLM_FAILURE_RETRY_DELAY_SEC=60
```

Partial edits are always discarded: an interrupted multi-file edit is not
reviewable evidence. The dumped diff is forensic only.

`inspect_repo_node` degrades instead of retrying: on transient failure,
`gather_evidence` returns partial evidence when it already collected tool
rounds, otherwise the node falls back to the pre-existing deterministic
keyword inspection and the run keeps moving. If the LLM is truly down, the
patch agent hits the failure next and owns the escalation.

### Layer 3 — human level (`llm_failure` mode)

When Layer 2 is exhausted, the run routes to the existing `human_review`
interrupt in a new mode instead of crashing:

- `BSPAgentState.failure_reason: str | None` is set with the error summary and
  acts as the mode discriminator (`llm_failure` when set, `patch_review`
  otherwise).
- The interrupt payload carries `mode` plus `failure_reason`, so the console
  renders Retry / Abandon instead of a diff with Approve / Reject.
- **Retry** (new resume action): clears `failure_reason` and routes back to
  `classify_error` **without** `new_attempt()` — the `max_loops` budget is
  untouched. Artifacts of the current attempt are overwritten (idempotent).
- **Abandon**: `abandon_run` (ADR-0008) is extended to accept
  `stage == "human_review" and failure_reason` — cleans the managed branch,
  releases the run lock, ends at `report`.
- `human_directed` is **not** set in `llm_failure` mode. That flag means "a
  human has made a quality judgment" (ADR-0009); pressing Retry is not one.
  It is never *unset* if already true.
- `approve` / `reject` are invalid in `llm_failure` mode; `retry` is invalid in
  `patch_review` mode.

Reusing `human_review` (instead of a parallel `failed` stage) gets the pause
semantics for free: the webhook path already keeps the run lock while
`stage == "human_review"`, `list_pending_runs` already surfaces such runs, and
resume rides the existing checkpointer interrupt — no new pipeline re-entry
mechanism.

### Expected behavior after this change

| Scenario | Outcome |
|---|---|
| Short blip (one or two failed requests) | absorbed by SDK retries; run unaffected |
| Load spike / server restart (~minutes) | absorbed by the delayed node retry |
| Legitimately slow large-prompt generation | absorbed by the 180 s timeout |
| Extended LLM outage | run pauses at `human_review` (`llm_failure`); budget intact; human presses Retry when the server is back, or Abandon |
| Model proposes a bad patch | unchanged: burns an attempt, retries with feedback |

## Consequences

- `human_review` now carries two modes; every consumer of the interrupt payload
  (console, CLI `review`) must branch on `mode`. The payload gains a `mode`
  field with `patch_review` as the default for backward compatibility.
- A paused `llm_failure` run holds the webhook run lock exactly like a
  patch-review pause. That is the intended single-working-tree serialization
  (ADR-0004); the pending list keeps it visible, and a future notification
  adapter plugs into the same place.
- Retry re-runs `classify_error -> select_skills -> load_skill -> inspect_repo`
  for the same attempt. These are cheap or degradable; per-attempt artifacts
  are overwritten in place.
- Non-transient exceptions (bugs, git failures) can still escape the graph and
  produce a zombie run. A pipeline-level safety net (`stage="failed"` +
  guaranteed lock/branch cleanup) is deliberately out of scope here and can be
  a follow-up ADR.
- The reject-path lock leak described in Context is fixed *for LLM failures*
  (they no longer escape the graph); the general 500-path remains until the
  safety-net follow-up.
