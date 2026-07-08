# MIC-741 Two-Stage Retrieval: FTS Recall + LLM Re-ranker

Add a second retrieval stage to the MIC-741 knowledge query: Postgres full-text
search stays as the wide recall stage (top-N cases), and a new LLM re-ranker
narrows those candidates to the top-K most relevant before they reach the patch
agent. The re-ranker calls the same self-hosted LLM endpoint the rest of the
pipeline uses.

Status: **Proposed**.

## Context

ADR-0013 built a case-based MIC-741 knowledge DB queried by Postgres FTS
(`tsvector`/`tsquery`, `ts_rank`). Phase 1 retrieves the top-N cases by `ts_rank`
and injects all of them into `repo_inspection.md` for the patch agent.

Measured behavior on a real camera issue ("Camera SIPL download is version-hardcoded,
refactor to parameterize and support v38.4.0") exposes two FTS-only failure modes:

```text
FTS returned 9 candidate cases:
  RE-17  camera  switch SIPL to r39.2.0     (related, wrong version)   <- ranked #1
  RE-07  camera  genericize SIPL + v38.4.0  (correct answer)          <- ranked #2
  RE-14  mgbe    customize AT7A1            (noise)
  RE-02  can     board config              (noise)
  ISSUE-G42005   nvpmodel                  (noise)
  ISSUE-G42006   LAN                       (noise)
  RE-01  mgbe    MDIO                       (noise)
  RE-06  can     SPI-CAN                    (noise)
  RE-08  can     mttcan                     (noise)
```

1. **Low precision.** 7 of 9 candidates only matched a shared token (e.g. the word
   "camera" appearing once in an unrelated file) and are irrelevant. Feeding 9 full
   cases dilutes the signal and burns context tokens.
2. **Wrong order on the relevant pair.** The distinguishing signal — the version
   `38.4.0` vs `39.2.0` — is lost to `simple` tokenization (`v38.4.0` -> `v38`, the
   data's `38.4.0` -> `38`), so `ts_rank` ties on `camera`+`sipl` frequency and puts
   RE-17 (wrong version) above RE-07 (the exact match). This is semantic
   disambiguation `ts_rank` structurally cannot do.

An LLM re-ranker reads the curated title / fix / files of each candidate and can
both drop the 7 noise cases and put RE-07 above RE-17, because the issue text
("parameterize + v38.4.0") matches RE-07's fix summary almost verbatim.

The earlier removal of the `subsystem=bug_type` filter (a vocabulary-mismatch bug)
left FTS returning cross-subsystem noise. The re-ranker subsumes that filtering
semantically, which is better than reintroducing a hard `bug_type -> subsystem` map.

## Decision

Two-stage retrieval inside `query_mic741_knowledge`:

```text
retrieve (FTS, top-N=10)  ->  re-rank (LLM, up to K=3)  ->  render markdown
     recall                        precision                  patch-agent context
```

Retrieval and rendering are separated so the re-ranker operates on structured rows
between them. `render_knowledge_matches` is unchanged; it simply receives the
re-ranked, truncated subset.

### Re-ranker contract

```python
_rerank_with_llm(issue: str, logs: list[str], rows: list[dict], settings) -> list[dict]
```

- Builds a compact candidate block from **curated fields only** — `case_key`,
  `subsystem`, `title`, `solution_summary`, `main_files`. It must **not** include the
  raw `matches` chunk (often a license header) which misleads the ranker.
- Candidates are presented **sorted by `case_key`**, not by FTS rank, to remove
  position bias (a weak model otherwise echoes the FTS order it is supposed to
  override).
- Calls `chat_completion` (the urllib choke point) with `temperature=0`,
  `name="mic741_rerank"`. Never `ChatOpenAI` — the choke point gives `LLMError`
  handling and avoids background LangSmith tracing.
- Parses strict JSON, normalizes and whitelist-filters the returned case keys,
  truncates to K.
- **Fail-open**: on `LLMError`, invalid JSON, or an empty result, return the FTS
  order truncated to K (`rows[:top_k]`). A broken re-ranker degrades to plain FTS,
  it never breaks the run.

### "Up to K", not "exactly K"

The prompt asks for *up to* K genuinely-relevant cases. For the camera example the
correct answer is 2 (RE-07, RE-17); forcing 3 would re-add a noise case. The model
may return fewer than K, and that is the desired behavior.

### `main_files` in `_query_rows`

Add a `files` CTE aggregating `repo_relative_path` from `mic741_case_files`
(`file_role in ('before','after','patch')`), null-filtered, capped at 3 paths per
case, exposed as `main_files` on each row. This is the only SQL change; files are a
strong relevance anchor for the re-ranker (same file touched -> likely same fix).

### `chat_completion` temperature

`chat_completion` gains an optional `temperature` parameter (default `0.1`,
backward compatible with its three existing callers). The re-ranker passes `0` for
determinism.

### Settings

```env
MIC741_RERANK_ENABLED=true      # off -> plain FTS top-N (unchanged behavior)
MIC741_RERANK_TOP_K=3
```

`MIC741_KNOWLEDGE_QUERY_LIMIT` (10) is unchanged and remains the recall width — the
re-ranker can only choose from what FTS surfaced, so N stays generous.

### Skip conditions

Re-ranking is skipped (rows returned as-is, truncated to K) when it is disabled or
when `len(rows) <= top_k` (nothing to narrow).

### Defensive parsing

The self-hosted model is weak at strict JSON. The parser must tolerate: fenced
JSON, leading/trailing prose, a bare string array vs an array of objects, full-stem
keys (`RE-07_camera-sipl-genericize` -> `RE-07` by prefix), hallucinated keys
(whitelist-filtered against the candidates), and more than K items (truncated).

## Artifacts and observability

- `name="mic741_rerank"` surfaces the call as a Langfuse generation alongside
  `select_skills` / `code_review`.
- Write `attempts/<n>/mic741_rerank.json`: the candidate case keys in, the model's
  ranked output (with `score` / `reason` when present), and whether a fallback
  occurred. This is the debug surface for "why these K".

## Expected trace (camera example)

```text
FTS(N=10)        -> 9 candidates (RE-07 at #2; 7 noise)
candidate block  -> case_key order; title/fix/files/subsystem only
LLM rerank(K=3, temp=0)
  -> {"ranked":[{"case_key":"RE-07","score":0.95,"reason":"same file, parameterize, v38.4.0"},
                {"case_key":"RE-17","score":0.6, "reason":"same file, different L4T version"}]}
  (returns 2, not 3 — nothing else is relevant)
parse -> whitelist filter -> [RE-07, RE-17]
render -> patch agent sees only these 2, RE-07 first
```

## Boundaries

- Re-ranking is read-only; it reorders and filters retrieved cases and nothing else.
- The DB schema is unchanged. `symbols` and embeddings remain unused/deferred.
- Failure always degrades to FTS order, never to an error.

## Deferred

- Embedding / hybrid semantic recall (still ADR-0013's deferred item).
- Symbol-overlap re-ranking as a cheaper deterministic alternative — the LLM
  re-ranker is chosen for accuracy; the symbol approach can layer in later.
- Letting the patch agent call knowledge search inside its own loop.

## Consequences

Precision improves markedly (9 -> ~2-3 curated cases) and the correct case is
ordered first, at the cost of one extra LLM call per attempt before patching
(bounded by `LLM_TIMEOUT_SEC`, one call, small token footprint). The re-ranker is
fail-open, so the worst case is exactly today's FTS behavior. `MIC741_RERANK_ENABLED=false`
reverts instantly.
