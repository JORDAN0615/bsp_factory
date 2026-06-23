# Jetson BSP Repair Agent — Pipeline (Node I/O)

This document defines the full repair pipeline as a sequence of nodes, each with
an explicit **input** and **output** contract. The rendered diagram is
`docs/pipeline.png` (source: `docs/pipeline.d2`, rendered with [D2](https://d2lang.com)).

```bash
d2 --layout elk --pad 30 docs/pipeline.d2 docs/pipeline.png
```

The inner repair loop is a LangGraph `StateGraph` (`agent/graph.py`). Everything
after `apply_patch` (build/flash, target registration, validation, report) is
CLI- and human-driven and lives outside the graph.

## Node contracts

Legend: **(LLM)** = LLM-backed, **(det.)** = deterministic, **(human)** =
human interrupt. Every node also reads/writes `state.json` and writes artifacts
under `runs/<run_id>/attempts/<n>/`.

| Node | Input | Output |
|---|---|---|
| `classify_error` (det.) | `issue`, `logs_text`, `known_error_patterns.yaml` | `bug_type`, `error_signatures`, `suspected_areas`; `debug/error_classification.json` |
| `select_skills` (LLM) | classification, full skill **catalog metadata** | `selected_skills` (≤ `max_selected_skills`, =3); `skill_selection.json`, `selected_skills.json`. Fallback: `known_error_patterns.yaml` |
| `load_skill` (det.) | `selected_skills`, `skills/` | `skill_text` = full `SKILL.md` of selected only; `debug/retrieved_skills.md` |
| `inspect_repo` (det.) | `repo_path`, attempt keywords | `repo_inspection` (rg search + safe read); `repo_inspection.md` |
| `patch_agent` (LLM) | `issue`, `skill_text`, `repo_inspection`, **retry context** | unified `diff_text` **or** `NO_PATCH`; `proposed_patch_prompt.md`, `proposed_patch_raw.md` |
| `validate_patch` (det.) | `diff_text` | normalized diff + `git apply --check` (**not applied**); on ok → `patch.md`, `changed_files`, `patch_status=generated`; on fail → `no_patch_reason` |
| `code_review_agent` (LLM) | `issue`, selected skill **names**, `repo_inspection`, `diff_text`, `code_review_policy.md`, retry context | strict JSON `{decision, confidence, findings, required_changes, human_required}`; `code_review.md`, `review_agent_raw.json`. Fail-safe → `needs_human`. **Never auto-approves — pass still routes to `human_review`** |
| `human_review` (human) | `patch.md`, `code_review.md`, attempt status | `approve` **or** `reject + feedback` (LangGraph `interrupt`, resumed by CLI) |
| `apply_patch` (det.) | canonical `patch.md` diff | `git apply` to working tree; `patch_status=applied`, `stage=target_ready` |
| `publish` (det., **NEW**) | applied tree, `git_remote`/branch | commit + push `bsp-agent/<run_id>`; `stage=published \| publish_failed`. **Opt-in, default OFF** (see ADR-0002) |
| `write_no_patch` (det.) | `no_patch_reason` | `no_patch.md`; next attempt **or** report |

### Post-approval (CLI + human-owned, outside the graph)

| Step | Input | Output |
|---|---|---|
| Human build/flash | approved/published source | flashed Jetson target (agent does not perform this) |
| `register-target` | `ssh_target`, human-declared `git_ref` | `TargetInfo` bound to run |
| `run-tests` (validation) | script under `tests/validation/` | upload + SSH run; **exit code is authoritative** |
| `report` | run state + artifacts | `report.md` |

## Routing and loops

The decision diamonds map 1:1 to the routing functions in `agent/graph.py`:

| Diamond | Source function | Branches |
|---|---|---|
| `diff?` | `route_after_patch_agent` | `diff` → `validate_patch`; `NO_PATCH` → `write_no_patch` |
| `git apply --check ok?` | `route_after_validate_patch` | valid → `code_review_agent`; invalid → `write_no_patch` |
| `review decision?` | `route_after_code_review` | **reject (retries left) → `classify_error`**; pass / needs_human / reject-exhausted → `human_review`. Human approval is always required — there is no auto-approve path |
| `human?` | `route_after_human_review` | approve → `apply_patch`; reject+feedback → `classify_error`; reject exhausted → report/END |
| `retries left?` | `route_after_no_patch` | yes → `classify_error`; exhausted → report/END |

### The Code Review retry loop (highlighted red in the diagram)

When `code_review_agent` returns **reject** and the retry budget is not
exhausted, the graph calls `state.new_attempt()` and routes back to
`classify_error`, which re-runs the whole inner chain down to `patch_agent`.
The reviewer's `findings` and `required_changes` are carried into the next
attempt through the **retry context**, so the Patch Agent does not repeat the
rejected patch. This is the "code review fail → back to the BSP agent → try
again" loop.

All retry loops (review reject, human reject, NO_PATCH, validation failure) are
bounded by `max_loops` (default 3). When the budget is exhausted, the run ends
at `report.md` instead of looping forever. The current in-progress attempt
never appears in its own retry context.

## Implemented vs planned

- Implemented today: every node above except `publish`.
- `publish` (agent git push after approval) is **planned** — see
  `docs/adr/0002-agent-push-after-approval.md`. Default OFF preserves the
  current "human owns commit/push/build/flash" boundary.
- The cronjob → git-issue automated trigger in the diagram is a **planned**
  ingestion path; only the manual `init-run` (Actor) path is implemented.
