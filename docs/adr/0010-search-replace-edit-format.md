# Search/Replace Edit Format

Replace the LLM's edit format from "unified diff + fuzzy hunk-header normalization"
with **search/replace blocks** applied by a small `str_replace`-style tool, the
approach Claude Code / Aider (editblock) / most agents converged on. This removes the
line-number / hunk-normalization fragility that blocks legitimate edits (e.g.
enabling several near-identical device-tree nodes).

Status: **Proposed**.

## Context

`patch_agent` currently emits a unified diff, and `validate_patch` runs
`normalize_hunk_headers` (a custom fuzzy re-placer) + `git apply --check`. The
normalizer ignores the model's line numbers, trims context to content-match, and on
repetitive files loses the unique context and fails with `old block is ambiguous`.
A real case: enabling four `mttcan@...` CAN controllers (`status "disabled" ->
"okay"`) failed because `status = "disabled";` occurs in many near-identical nodes.

Research on how agents edit code converges on two points:
- **Do not rely on line numbers** — they are unreliable; Aider deliberately drops
  them from hunk headers.
- **Require a unique match; on 0 or >1 matches, reject with an actionable error and
  let the model retry with more context** (Claude Code `str_replace`; Aider
  editblock; Pochi adds an expected-count for intentional multi-edits).

We already have a strong retry loop (automatic + human-directed, ADR-0009), so the
"actionable error -> model adapts" pattern fits directly.

We reimplement the approach (~small, dependency-free, model-agnostic) rather than
importing Claude's / Codex's tools, which are tied to their own model training.

## Decision

`patch_agent` emits **search/replace edit blocks**; a new `edit_tools` module
applies them by exact unique-context match. Git is still used to render the diff for
review and to commit — only the *model's edit format* changes.

### Model output format

```text
FILE: <repo-relative path>
REPLACE_ALL: <true|false>        # optional, default false
<<<<<<< SEARCH
<exact existing text, with enough surrounding context to be unique>
=======
<replacement text>
>>>>>>> REPLACE
```

Multiple blocks are allowed. `NO_PATCH <reason>` is still valid when no safe edit
exists.

### Apply semantics (`agent/tools/edit_tools.py`)

For each block, against the target file's current text:
- **exactly 1 occurrence** of SEARCH -> replace it.
- **0 occurrences** -> `EditError("SEARCH text not found in <file>; paste the exact
  current lines")`.
- **>1 occurrences** and `REPLACE_ALL` false -> `EditError("SEARCH text appears N
  times in <file>; add more surrounding context to make it unique, or set
  REPLACE_ALL: true")`.
- **>1 occurrences** and `REPLACE_ALL` true -> replace all N (the intended
  multi-node case, e.g. the CAN controllers).
- Target file must already exist inside the repo (new-file creation stays out of
  scope for the MVP, unchanged); path is sandboxed to the repo.

All `EditError`s are turned into a single actionable `NO_PATCH` reason, which feeds
the existing retry loop.

### Pipeline integration (keep validate/apply separation)

Human review happens between validation and application, so validation must not
write files:

- **`validate_patch`**: parse blocks; run the apply against **in-memory copies** to
  (a) verify every block matches uniquely / per `REPLACE_ALL`, and (b) produce a
  preview **unified diff** (via `difflib`/`git diff --no-index` on the would-be
  content) written to `patch.md`. Any `EditError` -> actionable NO_PATCH -> retry.
  `code_review_agent`, `human_review`, and the frontend keep seeing a normal diff.
- **`apply_patch`** (after human approval): perform the real writes on the working
  tree. `git diff` of the tree then drives commit/publish unchanged.

### What is retired

- `normalize_hunk_headers` and the git-apply-based validation for the LLM edit path.
  (`patch_tools.py` diff helpers may remain for rendering/summary; the fuzzy
  hunk re-placement is no longer on the path.)

## Boundaries

- Only the model's edit representation changes. `code_review`, `human_review`,
  `apply_patch -> publish`, ADR-0008 retry/abandon, ADR-0009 human-directed retry are
  unchanged; they continue to operate on the run's `patch.md` (a unified diff) and
  the working tree.
- New-file creation remains blocked (MVP), as today.
- Local model (Qwen) is not trained specifically on this format; the patch prompt
  must teach the format explicitly and the actionable errors carry recovery through
  the retry loop.

## Consequences

Legitimate edits to repetitive files (multiple identical DTS nodes) succeed via
`REPLACE_ALL` or per-node unique blocks instead of failing as "ambiguous". Edit
placement no longer depends on model-produced line numbers. The applier is ~small,
has no new dependency, and is model-agnostic. The cost is changing the patch prompt
and the validate/apply internals, and rerunning the patch tests against the new
format. Reviewers and humans are unaffected because they still see a unified diff.
