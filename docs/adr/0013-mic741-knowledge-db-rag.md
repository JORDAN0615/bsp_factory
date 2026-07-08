# MIC-741 Knowledge DB and Case-Based RAG

Build a MIC-741-specific knowledge database from the existing
`RAG_DOCS/MIC-741_KnowledgeBase` corpus. The database is case-based: the atomic
record is one historical repair case, not a loose document chunk. Each case
preserves the original issue, the human fix, the before/after code, and the patch
so the agent can retrieve "what was wrong and how it was fixed" for similar BSP
problems.

Status: **Proposed**.

## Context

The MIC-741 corpus already has three useful source layers:

```text
01_Issues/        issue markdown: symptom, goal, inferred solution, commit
02_Original_Code/ before/after source files plus patch per issue
03_Git_History/  commit history and full patch archive
```

The agent currently has short-term retry context inside one run, selected NVIDIA
BSP skills, deterministic repo inspection, and optional ReAct repo inspection.
It does not yet have long-term MIC-741 repair memory. For MIC-741 bring-up, the
most valuable knowledge is not isolated code snippets; it is the historical
mapping:

```text
issue / symptom -> touched files -> before code -> after code -> patch -> repair rule
```

That mapping is procedural memory: it tells the agent how a similar bug was fixed
before.

## Decision

Create a PostgreSQL-backed MIC-741 knowledge database. Phase 1 uses structured
tables plus PostgreSQL full-text search. Vector search and GraphRAG are deferred
until measured recall requires them.

The database's primary unit is a **repair case**:

```text
one issue, one fix history, one set of changed files
```

Examples:

```text
RE-07_camera-sipl-genericize
  Issue: Camera SIPL download is hardcoded to one L4T version.
  Fix: parameterize SIPL version / URL / MD5 and add v38.4.0 support.
  Files: source/config/task_download_after.sh
  Data: issue markdown + before file + after file + patch + repair rule.

ISSUE-G42006_LAN-MGBE
  Issue: MGBE connection fails on first boot.
  Fix: apply the historical network bring-up workaround.
  Files: main.sh, netplan yaml.
  Data: original DQA issue + before/after files + patch + repair rule.
```

## Data Model

### `mic741_cases`

One row per historical repair case.

```sql
create table mic741_cases (
  id uuid primary key,
  case_key text not null unique,
  issue_type text not null,          -- RE / ISSUE
  title text not null,
  subsystem text,                    -- camera / can / mgbe / pcie / pinmux / gpu / config
  platform text not null default 'MIC-741',
  jetpack_version text,
  l4t_version text,
  commit_sha text,
  source_issue_path text,
  source_case_dir text,
  issue_markdown text,
  solution_summary text,
  repair_rule text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

Required semantics:

- `case_key` is stable and human-readable, for example `RE-07` or
  `ISSUE-G42005`.
- `solution_summary` is a concise description of what the human fix did.
- `repair_rule` is the reusable procedural rule extracted from the case, for
  example "when Camera SIPL download is version-hardcoded, parameterize
  `TARGET_L4T_VERSION`, URL, and MD5 instead of adding another ad hoc branch."

### `mic741_case_files`

One row per file artifact attached to a case.

```sql
create table mic741_case_files (
  id uuid primary key,
  case_id uuid not null references mic741_cases(id) on delete cascade,
  file_role text not null,           -- issue / prompt / before / after / patch / history_patch
  file_path text not null,
  repo_relative_path text,
  language text,
  content text not null,
  content_hash text not null,
  created_at timestamptz not null default now()
);
```

Required semantics:

- `before` and `after` files preserve the complete file content from
  `02_Original_Code`.
- `patch` stores the human diff for that case.
- `repo_relative_path` is the path that the agent should compare against a live
  BSP repo, when known.

### `mic741_chunks`

Searchable slices derived from cases and files.

```sql
create table mic741_chunks (
  id uuid primary key,
  case_id uuid not null references mic741_cases(id) on delete cascade,
  file_id uuid references mic741_case_files(id) on delete cascade,
  chunk_type text not null,          -- issue / solution / repair_rule / before_code / after_code / patch_hunk / commit
  file_path text,
  content text not null,
  symbols text[] not null default '{}',
  search_vector tsvector generated always as (
    to_tsvector('simple', content)
  ) stored
);

create index mic741_chunks_fts_idx on mic741_chunks using gin(search_vector);
create index mic741_chunks_symbols_idx on mic741_chunks using gin(symbols);
create index mic741_cases_subsystem_idx on mic741_cases(subsystem);
```

`symbols` contains technical anchors extracted during preprocessing:

```text
CONFIG_* symbols
device-tree node names
compatible strings
file basenames
function names
error codes
JetPack / L4T versions
interface names such as mttcan, mgbe, pcie, sipl
```

## Preprocessing

Add an ingestion command or script that reads:

```text
RAG_DOCS/MIC-741_KnowledgeBase/01_Issues/*.md
RAG_DOCS/MIC-741_KnowledgeBase/02_Original_Code/<case>/
RAG_DOCS/MIC-741_KnowledgeBase/03_Git_History/patches/*.patch
```

For each case:

1. Parse the issue markdown for title, case key, commit sha, subsystem, main
   files, problem / goal, and actual solution.
2. Link the matching `02_Original_Code/<case>/` directory.
3. Store every `before/` and `after/` file as a full artifact.
4. Store the case patch (`*.patch` / `*.diff`) as the authoritative human diff.
5. Generate chunks from issue text, solution summary, repair rule, patch hunks,
   and relevant before/after code windows.
6. Extract symbols and version hints.
7. Upsert by `case_key` and `content_hash` so ingestion is repeatable.

The authoring format remains markdown/files in git. PostgreSQL is the query
format, not the source of truth.

## Query Contract

Expose a deterministic read-only query helper:

```python
query_mic741_knowledge(
    issue: str,
    logs: list[str],
    *,
    subsystem: str | None = None,
    limit: int = 10,
) -> str
```

The function returns prompt-ready markdown, not raw rows:

````md
## MIC-741 Knowledge Matches

### RE-07_camera-sipl-genericize
Subsystem: camera
Commit: 4e2f1bc
Main files:
- source/config/task_download_after.sh

Why matched:
- issue mentions Camera SIPL
- matched task_download_after.sh
- matched L4T version support

Historical issue:
...

Human fix:
...

Repair rule:
...

Patch excerpt:
```diff
...
```
````

The returned context must preserve case boundaries. The agent should be able to
see which issue produced which fix, instead of receiving unrelated fragments from
different cases.

## Pipeline Integration

Phase 1 integrates knowledge retrieval into the existing inspection context:

```text
classify_error
  -> select_skills
  -> load_skill
  -> retrieve_mic741_knowledge
  -> inspect_repo
  -> patch_agent
```

The implemented first integration is a dedicated `retrieve_mic741_knowledge`
node after skill loading and before repo inspection. It writes:

```text
attempts/<n>/mic741_knowledge.md
```

`inspect_repo_node` then receives that knowledge context and prepends it to
`repo_inspection.md`:

```md
## MIC-741 Knowledge Matches
...

## Repo Findings
...

## Source excerpts
...
```

`patch_agent` remains unchanged at first. It already consumes `repo_inspection`,
so the retrieved historical cases become part of the same evidence bundle as live
repo inspection.

## Boundaries

- The knowledge database is read-only during repair runs.
- Retrieval never writes source code, never applies patches, never commits, and
  never pushes.
- Ingestion is an explicit offline/admin step, not automatic during repair.
- Only successful or human-curated MIC-741 cases should enter the database.
- Phase 1 does not write back new run outcomes as memory. Approved/published run
  writeback is a later ADR.

## Deferred

- Vector embeddings / hybrid semantic search.
- GraphRAG over device-tree / driver / Kconfig relationships.
- Automatic extraction of new repair cases from approved BSP Agent runs.
- Cross-platform knowledge beyond MIC-741.
- Letting the patch agent directly call a knowledge-search tool inside its ReAct
  loop. The first integration is deterministic retrieval before patching.

## Consequences

The agent gains reusable MIC-741 procedural memory while keeping the repair graph
predictable. PostgreSQL full-text search is enough for the first version because
BSP bugs are dominated by exact technical anchors: file paths, Kconfig symbols,
device-tree nodes, compatible strings, L4T versions, and dmesg errors.

The cost is a new ingestion pipeline and schema migration surface. Keeping the
case as the primary unit avoids a common RAG failure mode: retrieving isolated
snippets that mention the right token but omit how the historical bug was
actually fixed.
