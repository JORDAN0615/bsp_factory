# Hunk-Aware Knowledge Injection

Replace the fixed-character patch-excerpt truncation with hunk-aware assembly:
split each retrieved case's patch into complete `@@` hunks, rank them by relevance
to the current issue, and inject complete hunks up to a budget — dropping whole
least-relevant hunks (with a visible marker) instead of blindly cutting the patch
mid-content at a fixed character count.

Status: **Proposed**.

## Context

The MIC-741 knowledge base exists so a domain-ignorant LLM can solve **novel** BSP
problems that have **no stored answer**: it learns from past similar change records,
the repair rule, and knowledge docs, then writes new code. The injected knowledge is
*guidance the LLM reasons from*, not a patch to replay — so it must reach the patch
agent complete and relevant.

Today `_query_rows` injects `patch_excerpt = left(patch_content, 5000)` — the first
5000 characters of the raw patch file. This silently drops real changes.

Measured on run `2026-07-08_145250` (RE-16, pinmux rsvd fix):

```text
RE-16 patch total: 6,610 chars   |   _PATCH_EXCERPT_CHARS = 5000
  @@ -1318  at char 1,695   shown -> agent reproduced it
  @@ -1968  at char 3,042   shown -> reproduced
  @@ -2018  at char 4,153   shown -> reproduced
  @@ -2030  at char 4,773   shown -> reproduced
  ---------- 5,000 cutoff ----------
  @@ -2090  at char 5,264   CUT    -> agent never saw it -> change missing
```

The agent reproduced exactly the hunks it was shown and dropped `@@ -2090` because it
fell past the cutoff. The DB held the full patch; the injection layer truncated it.

Two properties make a fixed character cap the wrong mechanism:

1. **Future change size is unpredictable** — file count and line count vary per issue,
   so any fixed number silently drops changes above it (RE-16 at 6.6K) while still
   failing to bound the outliers (RE-14 is 1.1 MB).
2. **It cuts by character offset, ignoring both hunk boundaries and relevance** — it
   can slice a hunk in half and it keeps the *first* bytes regardless of whether they
   are the most relevant to the current issue.

## Decision

Inject **complete hunks selected by relevance, bounded by a budget**, instead of a
raw character prefix. Never cut a hunk mid-content; when the budget is exceeded, drop
whole least-relevant hunks and record how many were omitted.

This operates on the patch text at query time from the stored `mic741_case_files`
content. No schema change and no re-ingestion.

### Flow

```text
_query_rows            -> returns full patch_content per case (no left(...,5000))
_rerank_with_llm       -> top-K cases (ADR-0014, unchanged)
per selected case:
  patch_excerpt = _select_relevant_hunks(patch_content, issue, logs, budget)
render_knowledge_matches  (unchanged — it already reads row["patch_excerpt"])
```

### `_select_relevant_hunks(patch_content, issue, logs, budget_chars) -> str`

1. **Split into hunk units.** Walk the patch; track the current file header
   (`diff --git ...` / `--- a/...` / `+++ b/...`). Each `@@ ... @@` block becomes one
   unit that carries its file header, so every unit is self-contained and shows which
   file it changes. A unit is never split further.
2. **Score each unit by relevance to the issue.** Anchors = `_extract_symbols(issue +
   logs)` plus issue keywords (file basenames, pin/interface names, CONFIG_ symbols,
   versions). A unit's score is how many distinct anchors appear in it.
3. **Greedy select complete units** in descending score until the next unit would
   exceed `budget_chars`. Ties keep original patch order.
4. **Re-emit selected units in original patch order** for readability.
5. **Mark omissions.** If any unit was dropped, append
   `... (N of M hunks omitted, ranked by relevance to this issue)`. Omission is
   visible, never silent.

When the whole patch fits the budget (RE-16 at 6.6K), every hunk is included — the
`@@ -2090` change is no longer dropped. When it does not (RE-14 at 1.1 MB), the most
relevant complete hunks are injected and the omission is stated, so the context window
is never blown and no change is silently lost.

### Setting

```env
# Per-case budget for injected patch hunks. Replaces the old 5000-char excerpt cap.
MIC741_KNOWLEDGE_HUNK_BUDGET_CHARS=16000
```

`_PATCH_EXCERPT_CHARS` is removed. The budget bounds **complete units**, not a byte
offset, so the size of any individual patch no longer causes partial loss.

### What is unchanged

- Case retrieval (FTS) and case re-ranking (ADR-0014) are untouched — this ADR changes
  only *what is injected per selected case*, not *which cases are selected*.
- Curated short fields (issue summary, human fix, repair rule) are still injected in
  full; they are what teach the *pattern* to a domain-ignorant LLM. Only the patch body
  — the large, variable part — becomes hunk-budgeted.
- `render_knowledge_matches` is unchanged; it keeps reading `row["patch_excerpt"]`.

## Boundaries

- This is an injection/assembly change. It does not apply patches, does not touch the
  schema, and requires no re-ingestion (it reads the already-stored patch content).
- Relevance scoring is lexical (symbol/keyword overlap). Semantic hunk relevance via
  embeddings is deferred (still ADR-0013's deferred item) and would slot into step 2.

## Deferred

- Embedding-based hunk relevance for the "semantically similar but no shared tokens"
  case — the true production need for novel problems.
- Global (cross-case) budget instead of per-case; per-case is simpler and the effective
  ceiling is `top_k * budget`, which is adequate for now.
- Storing patches pre-split at `@@` granularity in `mic741_chunks`; the query-time split
  avoids a re-ingest and is fast enough at this corpus size.

## Consequences

The domain-ignorant LLM receives complete, relevant change examples regardless of how
many files or lines a past fix touched, and never a hunk cut in half. RE-16 injects all
its hunks (the `@@ -2090` change returns); RE-14 injects a relevant, budget-bounded
subset with a visible omission note instead of blowing the context window. The design
serves the production goal — solving problems with no stored answer by teaching the
pattern — rather than the test-harness case where the answer already exists.
