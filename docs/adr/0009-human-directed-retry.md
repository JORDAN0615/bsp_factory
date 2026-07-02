# Human-Directed Retry

Once a run reaches `human_review`, a human reject **with feedback** must always
produce a fresh attempt that uses that feedback — it must never silently end the
run. The automatic retry budget (`max_loops`) bounds only the *automatic* loop, not
human-directed retries.

Status: **Proposed**.

## Context

`max_loops` (default 3) bounds the automatic reject / no-patch loop. When the
automatic loop is exhausted, the run escalates to `human_review` as a fallback
(see the code-review reject path). At that point the human is shown the last,
reviewer-rejected patch.

The bug: if the human then rejects with feedback, `human_review_node` runs
`if len(attempts) >= max_loops: stage = report`, so the run **ends immediately**.
The human's feedback is saved to `attempt.human_feedback` but **no new attempt ever
uses it** — the reject + suggestion is wasted. From the UI this looks like "I sent
reject + changes and it just stopped."

The root confusion is that `max_loops` conflates two different things:

```text
automatic retries      bounded (don't loop forever on the model alone)
human-directed retries a human explicitly asked for changes — much higher signal,
                       and self-limiting because each one requires a fresh human action
```

## Decision

Introduce **human-directed mode**. Once a run first reaches `human_review`, it is
human-directed for the rest of its life: it never silently ends at `report`; every
terminal outcome comes back to the human, who ends the run by **approving**
(publish) or **discarding** it.

Concretely:

1. **`human_review_node` reject → always a new attempt.** Remove the
   `len(attempts) >= max_loops -> report` branch. A human reject sets
   `human_feedback`, calls `state.new_attempt()`, and routes to `classify_error`,
   regardless of `max_loops`. The next patch attempt incorporates `human_feedback`
   (it already flows into the patch prompt via the review-feedback context).

2. **Mark the run human-directed.** Set `state.human_directed = True` in
   `human_review_node`.

3. **No silent `report` after the human is involved.** While `human_directed`:
   - `write_no_patch_node`: instead of ending at `report` when the budget is used
     up, route back to `human_review` (so "I tried your feedback but produced no
     patch" surfaces to the human, not a silent end). This needs a
     `write_no_patch -> human_review` edge.
   - `code_review_agent_node` reject already escalates to `human_review` when the
     budget is exhausted; that stays.

4. **Reject means "retry", not "end".** Ending a run is now only:
   - **approve** → apply + publish, or
   - **discard** (the separate abandon/discard action).
   The reject button therefore always means "try again with my feedback". The CLI /
   API already require non-empty feedback on reject, so this is consistent.

```text
auto loop (bounded by max_loops)
  reject / no_patch  -> retry ... -> exhausted -> escalate to human_review
human-directed (after first human_review)
  human reject+feedback -> NEW attempt (uses feedback) -> back to human_review
  human approve         -> apply_patch -> publish
  human discard         -> abandon/clean (ADR-0008 style)
```

## Boundaries

- `max_loops` still bounds the automatic loop before the first human escalation;
  it no longer caps human-directed retries.
- Human-directed retries cannot infinite-loop autonomously: each one requires the
  human to review the new attempt and reject again.
- No change to approve/publish/discard semantics; this only changes what reject does
  and removes silent `report` endings once a human is in the loop.

## Consequences

Human feedback is always used: a reject with suggestions produces a new,
feedback-informed attempt instead of being discarded. The mental model becomes
clean — approve accepts, reject retries, discard throws away — and a run that a
human has touched never ends without the human choosing how it ends. The cost is a
new `write_no_patch -> human_review` edge and a `human_directed` flag on the state.
