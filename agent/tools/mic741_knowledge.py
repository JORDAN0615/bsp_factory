from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.llm_tools import LLMConfig, LLMError, chat_completion, strip_json_fence

if TYPE_CHECKING:
    from agent.config import Settings


class KnowledgeDBError(RuntimeError):
    """Raised when MIC-741 knowledge DB setup, ingest, or query fails."""


class ReRankParseError(RuntimeError):
    """Raised when the MIC-741 LLM re-ranker returns unusable output."""


@dataclass(frozen=True)
class CaseFile:
    file_role: str
    file_path: str
    content: str
    repo_relative_path: str | None = None
    language: str | None = None
    content_hash: str = ""


@dataclass
class RepairCase:
    case_key: str
    issue_type: str
    title: str
    source_issue_path: str
    issue_markdown: str
    source_case_dir: str | None = None
    subsystem: str | None = None
    jetpack_version: str | None = None
    l4t_version: str | None = None
    commit_sha: str | None = None
    solution_summary: str = ""
    repair_rule: str = ""
    files: list[CaseFile] = field(default_factory=list)


SCHEMA_SQL = """
create table if not exists mic741_cases (
  id uuid primary key,
  case_key text not null unique,
  issue_type text not null,
  title text not null,
  subsystem text,
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

create table if not exists mic741_case_files (
  id uuid primary key,
  case_id uuid not null references mic741_cases(id) on delete cascade,
  file_role text not null,
  file_path text not null,
  repo_relative_path text,
  language text,
  content text not null,
  content_hash text not null,
  created_at timestamptz not null default now()
);

create table if not exists mic741_chunks (
  id uuid primary key,
  case_id uuid not null references mic741_cases(id) on delete cascade,
  file_id uuid references mic741_case_files(id) on delete cascade,
  chunk_type text not null,
  file_path text,
  content text not null,
  symbols text[] not null default '{}',
  search_vector tsvector
);

create index if not exists mic741_chunks_fts_idx on mic741_chunks using gin(search_vector);
create index if not exists mic741_chunks_symbols_idx on mic741_chunks using gin(symbols);
create index if not exists mic741_cases_subsystem_idx on mic741_cases(subsystem);
"""

_MAX_TEXT_ARTIFACT_BYTES = 2_000_000
_CHUNK_CHARS = 4000
_MATCH_EXCERPT_CHARS = 1200


def init_schema(db_url: str) -> None:
    with _connect(db_url) as conn:
        _execute_schema(conn)


def ingest_mic741_knowledge(source_dir: str | Path, db_url: str) -> dict[str, int]:
    source = Path(source_dir)
    cases = parse_mic741_cases(source)
    with _connect(db_url) as conn:
        _execute_schema(conn)
        for case in cases:
            _upsert_case(conn, case)
    return {
        "cases": len(cases),
        "files": sum(len(case.files) for case in cases),
    }


def query_mic741_knowledge(
    issue: str,
    logs: list[str],
    settings: "Settings",
    *,
    subsystem: str | None = None,
    limit: int | None = None,
    debug_dir: str | Path | None = None,
) -> str:
    if not settings.mic741_knowledge_db_url:
        raise KnowledgeDBError("MIC741_KNOWLEDGE_DB_URL is not configured")
    query_text = "\n".join([issue, *logs]).strip()
    if not query_text:
        return ""
    fts_query = _fts_query_text(query_text)
    if not fts_query:
        return ""
    rows = _query_rows(
        settings.mic741_knowledge_db_url,
        fts_query,
        subsystem=subsystem,
        limit=limit or settings.mic741_knowledge_query_limit,
    )
    top_k = settings.mic741_rerank_top_k
    if settings.mic741_rerank_enabled and len(rows) > top_k:
        rows = _rerank_with_llm(issue, logs, rows, settings, debug_dir=debug_dir)
    for row in rows:
        row["patch_excerpt"] = _select_relevant_hunks(
            str(row.pop("patch_content", "") or ""),
            issue,
            logs,
            settings.mic741_knowledge_hunk_budget_chars,
        )
    return render_knowledge_matches(rows)


def parse_mic741_cases(source_dir: str | Path) -> list[RepairCase]:
    source = Path(source_dir)
    issues_dir = source / "01_Issues"
    code_dir = source / "02_Original_Code"
    if not issues_dir.is_dir():
        raise KnowledgeDBError(f"MIC-741 issue directory not found: {issues_dir}")
    cases: list[RepairCase] = []
    for issue_path in sorted(issues_dir.glob("*.md")):
        if issue_path.name.upper() in {"README.MD", "RE-INDEX.MD"}:
            continue
        issue_markdown = issue_path.read_text(encoding="utf-8", errors="replace")
        case_key = _case_key_from_stem(issue_path.stem)
        case_dir = _find_case_dir(code_dir, case_key)
        case = RepairCase(
            case_key=case_key,
            issue_type="ISSUE" if case_key.startswith("ISSUE-") else "RE",
            title=_extract_title(issue_markdown, issue_path.stem),
            source_issue_path=_rel_to_source(issue_path, source),
            issue_markdown=issue_markdown,
            source_case_dir=_rel_to_source(case_dir, source) if case_dir else None,
            subsystem=_infer_subsystem(issue_path.stem, issue_markdown),
            jetpack_version=_extract_version(issue_markdown, r"JetPack\s*([0-9.]+)"),
            l4t_version=_extract_version(issue_markdown, r"L4T\s*r?([0-9.]+)"),
            commit_sha=_extract_commit(issue_markdown),
            solution_summary=_extract_section(issue_markdown, ["解法", "實際 commit 做法"]),
        )
        case.repair_rule = _build_repair_rule(case)
        case.files.append(_case_file("issue", issue_path, source, issue_path.name, issue_markdown))
        if case_dir:
            case.files.extend(_collect_case_files(case_dir, source))
        cases.append(case)
    return cases


def render_knowledge_matches(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "## MIC-741 Knowledge Matches\n\nNo MIC-741 repair cases matched.\n"

    lines = ["## MIC-741 Knowledge Matches", ""]
    for index, row in enumerate(rows, start=1):
        title = str(row.get("title") or row.get("case_key") or "untitled")
        case_key = str(row.get("case_key") or "unknown")
        lines.extend(
            [
                f"### {index}. {case_key} - {title}",
                f"Subsystem: {row.get('subsystem') or '(unknown)'}",
                f"Commit: {row.get('commit_sha') or '(unknown)'}",
                "",
                "Why matched:",
            ]
        )
        for match in _as_list(row.get("matches"))[:3]:
            lines.append(f"- {_one_line(match, _MATCH_EXCERPT_CHARS)}")
        if not row.get("matches"):
            lines.append("- matched by full-text search")
        lines.extend(
            [
                "",
                "Historical issue:",
                _strip_md_heading(str(row.get("issue_markdown") or ""), _MATCH_EXCERPT_CHARS),
                "",
                "Human fix:",
                str(row.get("solution_summary") or "(not extracted)"),
                "",
                "Repair rule:",
                str(row.get("repair_rule") or "(not extracted)"),
                "",
            ]
        )
        patch_excerpt = str(row.get("patch_excerpt") or "").strip()
        if patch_excerpt:
            lines.extend(["Patch excerpt:", "```diff", patch_excerpt, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def _connect(db_url: str):
    if not db_url:
        raise KnowledgeDBError("MIC741_KNOWLEDGE_DB_URL is not configured")
    try:
        import psycopg
    except ImportError as exc:
        raise KnowledgeDBError("psycopg is required for MIC-741 knowledge DB") from exc
    try:
        return psycopg.connect(db_url)
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeDBError(str(exc)) from exc


def _execute_schema(conn: Any) -> None:
    for statement in [part.strip() for part in SCHEMA_SQL.split(";") if part.strip()]:
        conn.execute(statement)


def _upsert_case(conn: Any, case: RepairCase) -> None:
    case_id = uuid.uuid5(uuid.NAMESPACE_URL, f"mic741:{case.case_key}")
    conn.execute(
        """
        insert into mic741_cases (
          id, case_key, issue_type, title, subsystem, jetpack_version, l4t_version,
          commit_sha, source_issue_path, source_case_dir, issue_markdown,
          solution_summary, repair_rule
        ) values (
          %(id)s, %(case_key)s, %(issue_type)s, %(title)s, %(subsystem)s,
          %(jetpack_version)s, %(l4t_version)s, %(commit_sha)s, %(source_issue_path)s,
          %(source_case_dir)s, %(issue_markdown)s, %(solution_summary)s, %(repair_rule)s
        )
        on conflict (case_key) do update set
          issue_type = excluded.issue_type,
          title = excluded.title,
          subsystem = excluded.subsystem,
          jetpack_version = excluded.jetpack_version,
          l4t_version = excluded.l4t_version,
          commit_sha = excluded.commit_sha,
          source_issue_path = excluded.source_issue_path,
          source_case_dir = excluded.source_case_dir,
          issue_markdown = excluded.issue_markdown,
          solution_summary = excluded.solution_summary,
          repair_rule = excluded.repair_rule,
          updated_at = now()
        """,
        {
            "id": case_id,
            "case_key": case.case_key,
            "issue_type": case.issue_type,
            "title": case.title,
            "subsystem": case.subsystem,
            "jetpack_version": case.jetpack_version,
            "l4t_version": case.l4t_version,
            "commit_sha": case.commit_sha,
            "source_issue_path": case.source_issue_path,
            "source_case_dir": case.source_case_dir,
            "issue_markdown": case.issue_markdown,
            "solution_summary": case.solution_summary,
            "repair_rule": case.repair_rule,
        },
    )
    conn.execute("delete from mic741_case_files where case_id = %s", (case_id,))
    conn.execute("delete from mic741_chunks where case_id = %s", (case_id,))
    for artifact in case.files:
        file_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mic741:{case.case_key}:{artifact.file_role}:{artifact.file_path}",
        )
        conn.execute(
            """
            insert into mic741_case_files (
              id, case_id, file_role, file_path, repo_relative_path, language,
              content, content_hash
            ) values (
              %(id)s, %(case_id)s, %(file_role)s, %(file_path)s, %(repo_relative_path)s,
              %(language)s, %(content)s, %(content_hash)s
            )
            """,
            {
                "id": file_id,
                "case_id": case_id,
                "file_role": artifact.file_role,
                "file_path": artifact.file_path,
                "repo_relative_path": artifact.repo_relative_path,
                "language": artifact.language,
                "content": artifact.content,
                "content_hash": artifact.content_hash or _sha256(artifact.content),
            },
        )
        for chunk_type, content in _chunks_for_file(artifact):
            _insert_chunk(conn, case_id, file_id, chunk_type, artifact.repo_relative_path, content)
    for chunk_type, content in [
        ("issue", case.issue_markdown),
        ("solution", case.solution_summary),
        ("repair_rule", case.repair_rule),
    ]:
        if content.strip():
            _insert_chunk(conn, case_id, None, chunk_type, None, content)


def _insert_chunk(
    conn: Any,
    case_id: uuid.UUID,
    file_id: uuid.UUID | None,
    chunk_type: str,
    file_path: str | None,
    content: str,
) -> None:
    for chunk in _split_chunks(content):
        conn.execute(
            """
            insert into mic741_chunks (
              id, case_id, file_id, chunk_type, file_path, content, symbols, search_vector
            ) values (
              %(id)s, %(case_id)s, %(file_id)s, %(chunk_type)s, %(file_path)s,
              %(content)s, %(symbols)s, to_tsvector('simple', %(content)s)
            )
            """,
            {
                "id": uuid.uuid4(),
                "case_id": case_id,
                "file_id": file_id,
                "chunk_type": chunk_type,
                "file_path": file_path,
                "content": chunk,
                "symbols": _extract_symbols(chunk),
            },
        )


def _query_rows(
    db_url: str,
    query_text: str,
    *,
    subsystem: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise KnowledgeDBError("psycopg is required for MIC-741 knowledge DB") from exc
    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
            with q as (
              select to_tsquery('simple', %(query)s) as query
            ),
            ranked as (
              select
                c.id as case_id,
                c.case_key,
                c.title,
                c.subsystem,
                c.commit_sha,
                c.issue_markdown,
                c.solution_summary,
                c.repair_rule,
                ch.content,
                ts_rank(ch.search_vector, q.query) as rank
              from mic741_chunks ch
              join mic741_cases c on c.id = ch.case_id
              cross join q
              where ch.search_vector @@ q.query
                and (%(subsystem)s::text is null or c.subsystem = %(subsystem)s::text)
            ),
            top_cases as (
              select case_id, max(rank) as best_rank
              from ranked
              group by case_id
              order by best_rank desc
              limit %(limit)s
            ),
            patches as (
              select distinct on (case_id)
                case_id,
                content as patch_content
              from mic741_case_files
              where file_role in ('patch', 'history_patch')
              order by case_id, file_path
            ),
            files as (
              select
                case_id,
                (array_agg(distinct repo_relative_path)
                  filter (where repo_relative_path is not null))[1:3] as main_files
              from mic741_case_files
              where file_role in ('before', 'after', 'patch')
              group by case_id
            )
            select
              r.case_key,
              r.title,
              r.subsystem,
              r.commit_sha,
              r.issue_markdown,
              r.solution_summary,
              r.repair_rule,
              array_agg(left(r.content, %(match_chars)s) order by r.rank desc) as matches,
              p.patch_content,
              fl.main_files
            from top_cases t
            join ranked r on r.case_id = t.case_id
            left join patches p on p.case_id = t.case_id
            left join files fl on fl.case_id = t.case_id
            group by
              t.best_rank, r.case_key, r.title, r.subsystem, r.commit_sha,
              r.issue_markdown, r.solution_summary, r.repair_rule, p.patch_content,
              fl.main_files
            order by t.best_rank desc
            """,
                {
                    "query": query_text,
                    "subsystem": subsystem,
                    "limit": limit,
                    "match_chars": _MATCH_EXCERPT_CHARS,
                },
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeDBError(str(exc)) from exc
    return list(rows)


def _rerank_with_llm(
    issue: str,
    logs: list[str],
    rows: list[dict[str, Any]],
    settings: "Settings",
    debug_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    top_k = settings.mic741_rerank_top_k
    messages = _build_rerank_messages(issue, logs, rows, top_k)
    fallback = False
    picked_keys: list[str] = []
    picked_items: list[dict[str, Any]] = []
    try:
        raw = chat_completion(
            LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model),
            messages,
            timeout_sec=settings.llm_timeout_sec,
            name="mic741_rerank",
            temperature=0,
        )
        picked_items = _parse_rerank(raw)
        valid_keys = {str(row.get("case_key") or "") for row in rows}
        for item in picked_items:
            key = _normalize_case_key(str(item.get("case_key") or ""), valid_keys)
            if key and key not in picked_keys:
                picked_keys.append(key)
    except (LLMError, ReRankParseError):
        fallback = True

    by_key = {str(row.get("case_key") or ""): row for row in rows}
    reranked = [by_key[key] for key in picked_keys if key in by_key][:top_k]
    if not reranked:
        fallback = True
        reranked = rows[:top_k]
    if debug_dir is not None:
        _write_rerank_artifact(debug_dir, rows, picked_items, picked_keys, fallback)
    return reranked


def _split_hunk_units(patch_content: str) -> list[str]:
    """Split a unified diff into self-contained file-header + hunk units."""
    units: list[str] = []
    header: list[str] = []
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            units.append("".join(header + current))
            current = None

    for line in patch_content.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            header = [line]
        elif line.startswith("@@"):
            flush()
            current = [line]
        elif current is not None:
            current.append(line)
        elif line.startswith(
            (
                "index ",
                "--- ",
                "+++ ",
                "new file",
                "deleted file",
                "old mode",
                "new mode",
                "similarity ",
                "rename ",
                "copy ",
            )
        ):
            header.append(line)
    flush()
    return units


def _select_relevant_hunks(
    patch_content: str,
    issue: str,
    logs: list[str],
    budget_chars: int,
) -> str:
    """Assemble complete patch hunks up to a relevance-ranked budget."""
    units = _split_hunk_units(patch_content)
    if not units:
        return ""
    anchors = _knowledge_anchors("\n".join([issue, *logs]))

    def score(unit: str) -> int:
        low = unit.lower()
        return sum(1 for anchor in anchors if anchor in low)

    scored = [(index, score(unit), unit) for index, unit in enumerate(units)]
    order = sorted(scored, key=lambda item: (-item[1], item[0]))
    chosen: set[int] = set()
    total = 0
    for index, _, unit in order:
        if chosen and total + len(unit) > budget_chars:
            continue
        chosen.add(index)
        total += len(unit)
    result = "".join(unit for index, _, unit in scored if index in chosen).strip()
    omitted = len(units) - len(chosen)
    if omitted:
        result += (
            f"\n... ({len(chosen)} of {len(units)} hunks shown, "
            f"ranked by relevance to this issue; {omitted} omitted)"
        )
    return result


def _knowledge_anchors(text: str) -> set[str]:
    anchors = {anchor.lower() for anchor in _extract_symbols(text)}
    for token in re.findall(r"[A-Za-z0-9_+./-]{3,}", text):
        cleaned = token.lower().strip(".,:;()[]{}'\"`")
        if cleaned:
            anchors.add(cleaned)
            anchors.add(Path(cleaned).name)
    return anchors


def _build_rerank_messages(
    issue: str,
    logs: list[str],
    rows: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, str]]:
    candidates = sorted(rows, key=lambda row: str(row.get("case_key") or ""))
    candidate_blocks: list[str] = []
    for row in candidates:
        main_files = ", ".join(_as_list(row.get("main_files"))[:3]) or "(unknown)"
        candidate_blocks.append(
            "\n".join(
                [
                    f"[{row.get('case_key')}] subsystem={row.get('subsystem') or '(unknown)'}",
                    f"  title: {row.get('title') or '(untitled)'}",
                    f"  fix:   {_one_line(str(row.get('solution_summary') or ''), 500)}",
                    f"  files: {main_files}",
                ]
            )
        )
    log_text = "\n".join(logs)[:1500]
    candidate_text = "\n\n".join(candidate_blocks)
    return [
        {
            "role": "system",
            "content": (
                "You are a relevance ranker for Jetson BSP repair cases. "
                f"Select up to {top_k} cases whose past fix would actually help THIS new issue. "
                "Judge by subsystem, same files, symptom, interface, and version. "
                "A case that only shares a keyword but fixed a different problem is not relevant. "
                "Return strict JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Issue:\n{issue}\n\n"
                f"Logs:\n{log_text or '(none)'}\n\n"
                "Candidate repair cases, sorted by case_key:\n\n"
                f"{candidate_text}\n\n"
                "Return JSON only in this shape:\n"
                '{"ranked":[{"case_key":"RE-07","score":0.0,"reason":"one line"}]}\n'
                "Use only case_key values from the candidate list. Best case first. "
                f"Return up to {top_k}; return fewer when fewer are genuinely relevant."
            ),
        },
    ]


def _parse_rerank(raw: str) -> list[dict[str, Any]]:
    parsed = _load_rerank_json(raw)
    if isinstance(parsed, dict):
        items = parsed.get("ranked")
    else:
        items = parsed
    if not isinstance(items, list):
        raise ReRankParseError("rerank output does not contain a list")
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            normalized.append({"case_key": item})
        elif isinstance(item, dict) and item.get("case_key"):
            normalized.append(dict(item))
    if not normalized:
        raise ReRankParseError("rerank output contains no case keys")
    return normalized


def _load_rerank_json(raw: str) -> Any:
    cleaned = strip_json_fence(raw).strip()
    candidates = [cleaned]
    object_start = cleaned.find("{")
    object_end = cleaned.rfind("}")
    if object_start != -1 and object_end > object_start:
        candidates.append(cleaned[object_start : object_end + 1])
    array_start = cleaned.find("[")
    array_end = cleaned.rfind("]")
    if array_start != -1 and array_end > array_start:
        candidates.append(cleaned[array_start : array_end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ReRankParseError("rerank output is not valid JSON")


def _normalize_case_key(raw_key: str, valid_keys: set[str]) -> str:
    key = raw_key.strip()
    if key in valid_keys:
        return key
    for valid in sorted(valid_keys, key=len, reverse=True):
        if key.startswith(f"{valid}_") or key.startswith(f"{valid}-"):
            return valid
    return ""


def _write_rerank_artifact(
    debug_dir: str | Path,
    rows: list[dict[str, Any]],
    picked_items: list[dict[str, Any]],
    picked_keys: list[str],
    fallback: bool,
) -> None:
    from agent.tools.artifact_tools import write_json

    write_json(
        Path(debug_dir) / "mic741_rerank.json",
        {
            "candidates": [row.get("case_key") for row in rows],
            "picked": picked_items,
            "picked_keys": picked_keys,
            "fallback": fallback,
        },
    )


def _collect_case_files(case_dir: Path, source: Path) -> list[CaseFile]:
    files: list[CaseFile] = []
    for path in sorted(case_dir.rglob("*")):
        if not path.is_file() or _is_ignored(path):
            continue
        role = _file_role(path, case_dir)
        content = _read_text_artifact(path)
        if content is None:
            continue
        repo_relative = _repo_relative_path(path, case_dir)
        files.append(_case_file(role, path, source, _rel_to_source(path, source), content, repo_relative))
    return files


def _fts_query_text(text: str) -> str:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[0-9]+", text)
    stop = {
        "after",
        "with",
        "and",
        "the",
        "for",
        "from",
        "this",
        "that",
        "failed",
        "fails",
        "failure",
        "support",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        clean = token.lower().strip("_+-")
        if len(clean) < 2 or clean in stop or clean in seen:
            continue
        seen.add(clean)
        terms.append(clean)
        if len(terms) >= 16:
            break
    return " | ".join(terms)


def _case_file(
    role: str,
    path: Path,
    source: Path,
    file_path: str,
    content: str,
    repo_relative_path: str | None = None,
) -> CaseFile:
    return CaseFile(
        file_role=role,
        file_path=file_path,
        repo_relative_path=repo_relative_path,
        language=_language_for_path(path),
        content=content,
        content_hash=_sha256(content),
    )


def _chunks_for_file(file: CaseFile) -> list[tuple[str, str]]:
    if file.file_role == "patch" or file.file_role == "history_patch":
        return [("patch_hunk", chunk) for chunk in _split_patch_hunks(file.content)]
    if file.file_role in {"before", "after"}:
        return [(f"{file.file_role}_code", file.content)]
    if file.file_role in {"issue", "prompt"}:
        return [(file.file_role, file.content)]
    return [("commit", file.content)]


def _split_chunks(content: str) -> list[str]:
    text = content.strip()
    if not text:
        return []
    return [text[index : index + _CHUNK_CHARS] for index in range(0, len(text), _CHUNK_CHARS)]


def _split_patch_hunks(content: str) -> list[str]:
    parts = re.split(r"(?=^diff --git )", content, flags=re.MULTILINE)
    return [part.strip() for part in parts if part.strip()]


def _extract_symbols(content: str) -> list[str]:
    patterns = [
        r"\bCONFIG_[A-Za-z0-9_]+\b",
        r"\b[A-Za-z0-9_+.-]+@[0-9a-fA-F]+\b",
        r'compatible\s*=\s*"([^"]+)"',
        r"\b(?:i2c|spi|pcie|mttcan|mgbe|sipl|nvpmodel|pinmux|gpio)[A-Za-z0-9_.-]*\b",
        r"\b(?:JP|JetPack|L4T|r)[0-9]+(?:\.[0-9]+)+\b",
        r"\b-\d{2,4}\b",
    ]
    symbols: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, content, flags=re.IGNORECASE):
            value = match.group(1) if match.lastindex else match.group(0)
            symbols.add(value)
    return sorted(symbols)[:100]


def _read_text_artifact(path: Path) -> str | None:
    if path.stat().st_size > _MAX_TEXT_ARTIFACT_BYTES:
        return None
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _file_role(path: Path, case_dir: Path) -> str:
    parts = path.relative_to(case_dir).parts
    if parts and parts[0] in {"before", "after"}:
        return parts[0]
    suffix = path.suffix.lower()
    if suffix in {".patch", ".diff"}:
        return "patch"
    if path.name.upper() == "PROMPT.MD":
        return "prompt"
    return "case_artifact"


def _repo_relative_path(path: Path, case_dir: Path) -> str | None:
    parts = path.relative_to(case_dir).parts
    if len(parts) >= 3 and parts[0] in {"before", "after"}:
        return str(Path(*parts[1:]))
    return None


def _find_case_dir(code_dir: Path, case_key: str) -> Path | None:
    if not code_dir.is_dir():
        return None
    matches = sorted(path for path in code_dir.iterdir() if path.is_dir() and path.name.startswith(case_key))
    return matches[0] if matches else None


def _case_key_from_stem(stem: str) -> str:
    if stem.startswith("RE-"):
        parts = stem.split("_", 1)
        return parts[0]
    if stem.startswith("ISSUE-"):
        parts = stem.split("_", 1)
        return parts[0]
    return stem


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.lstrip("#").strip()
    return fallback


def _extract_commit(markdown: str) -> str | None:
    match = re.search(r"`([0-9a-f]{7,40})`", markdown, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_version(markdown: str, pattern: str) -> str | None:
    match = re.search(pattern, markdown, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_section(markdown: str, headings: list[str]) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("##"):
            continue
        if not any(heading.lower() in line.lower() for heading in headings):
            continue
        body: list[str] = []
        for next_line in lines[index + 1 :]:
            if next_line.startswith("##"):
                break
            body.append(next_line)
        return "\n".join(body).strip()
    return ""


def _build_repair_rule(case: RepairCase) -> str:
    summary = _one_line(case.solution_summary, 500) if case.solution_summary else ""
    if summary:
        return f"For similar {case.subsystem or 'MIC-741'} issues, use the historical fix pattern: {summary}"
    return f"For similar {case.subsystem or 'MIC-741'} issues, inspect the same files and compare before/after code from {case.case_key}."


def _infer_subsystem(name: str, text: str) -> str | None:
    haystack = f"{name}\n{text}".lower()
    keywords = {
        "camera": ["camera", "sipl", "imx"],
        "can": ["can", "mttcan", "mcp2518fd"],
        "mgbe": ["mgbe", "aquantia", "lan", "ethernet"],
        "pcie": ["pcie", "nvme"],
        "pinmux": ["pinmux", "gpio", "i2c"],
        "gpu": ["gpu", "nvpmodel"],
        "config": ["config", "download", "som", "flash"],
    }
    for subsystem, terms in keywords.items():
        if any(term in haystack for term in terms):
            return subsystem
    return None


def _language_for_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    mapping = {
        ".dts": "dts",
        ".dtsi": "dts",
        ".conf": "conf",
        ".mk": "make",
        ".sh": "shell",
        ".patch": "patch",
        ".diff": "patch",
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".c": "c",
        ".h": "c",
    }
    return mapping.get(suffix)


def _is_ignored(path: Path) -> bool:
    return path.name == ".DS_Store" or path.name.startswith("._")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _rel_to_source(path: Path, source: Path) -> str:
    return str(path.relative_to(source))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _strip_md_heading(markdown: str, max_chars: int) -> str:
    lines = [line for line in markdown.splitlines() if line.strip()]
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return _one_line("\n".join(lines), max_chars)


def _one_line(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return f"{clean[: max_chars - 3]}..."
