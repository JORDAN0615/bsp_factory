from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.artifact_tools import write_json
from agent.tools.mic741_knowledge import (
    KnowledgeDBError,
    _connect,
    _fts_query_text,
    _query_rows,
    _select_relevant_hunks,
)
from agent.tools.reranker import rerank

if TYPE_CHECKING:
    from agent.config import Settings


def _fts_query_text_prefix(text: str) -> str:
    """Build a prefix-aware tsquery without changing the existing tokenizer."""
    base = _fts_query_text(text)
    if not base:
        return ""
    terms: list[str] = []
    for raw_term in base.split("|"):
        term = raw_term.strip()
        if not term:
            continue
        terms.append(term)
        has_embedded_digits = bool(re.fullmatch(r"[a-z]+\d+[a-z]+", term))
        if len(term) >= 3 and (term.isalpha() or has_embedded_digits):
            terms.append(f"{term}:*")
    return " | ".join(terms)


def _query_doc_candidates(
    db_url: str,
    query_text: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise KnowledgeDBError("psycopg is required for document knowledge DB") from exc

    params = {"query": query_text, "limit": limit}
    try:
        with _connect(db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    with q as (
                      select to_tsquery('simple', %(query)s) as query
                    )
                    select
                      'document' as source_type,
                      dc.id::text as candidate_id,
                      ds.doc_key,
                      ds.title,
                      ds.platform,
                      ds.doc_version,
                      dc.chunk_type,
                      dc.section_path,
                      dc.page,
                      dc.content,
                      null::text as ball,
                      null::text as signal_name,
                      ts_rank(dc.search_vector, q.query) as rank
                    from doc_chunks dc
                    join doc_sources ds on ds.id = dc.source_id
                    cross join q
                    where dc.search_vector @@ q.query
                    order by rank desc
                    limit %(limit)s
                    """,
                    params,
                )
                chunks = list(cursor.fetchall())
                cursor.execute(
                    """
                    with q as (
                      select to_tsquery('simple', %(query)s) as query
                    )
                    select
                      'pinmux pin' as source_type,
                      pp.id::text as candidate_id,
                      ds.doc_key,
                      ds.title,
                      coalesce(pp.platform, ds.platform) as platform,
                      ds.doc_version,
                      'pinmux_pin' as chunk_type,
                      null::text as section_path,
                      null::int as page,
                      pp.content,
                      pp.ball,
                      pp.signal_name,
                      ts_rank(pp.search_vector, q.query) as rank
                    from pinmux_pins pp
                    join doc_sources ds on ds.id = pp.source_id
                    cross join q
                    where pp.search_vector @@ q.query
                    order by rank desc
                    limit %(limit)s
                    """,
                    params,
                )
                pins = list(cursor.fetchall())
    except KnowledgeDBError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeDBError(str(exc)) from exc
    return sorted(
        [*chunks, *pins],
        key=lambda row: float(row.get("rank") or 0.0),
        reverse=True,
    )[:limit]


def _case_candidate(row: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(row)
    candidate["source_type"] = "MIC-741 case"
    parts = [
        str(row.get("title") or ""),
        str(row.get("issue_markdown") or ""),
        str(row.get("solution_summary") or ""),
        str(row.get("repair_rule") or ""),
        "\n".join(str(match) for match in row.get("matches") or []),
    ]
    candidate["content"] = "\n\n".join(part for part in parts if part.strip())
    return candidate


def _rank_candidates(
    issue: str,
    candidates: list[dict[str, Any]],
    settings: "Settings",
    *,
    debug_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    ranked_pairs = rerank(
        issue,
        [str(candidate.get("content") or "") for candidate in candidates],
        settings.rerank_top_k,
        settings,
    )
    ranked: list[dict[str, Any]] = []
    for index, score in ranked_pairs:
        candidate = dict(candidates[index])
        candidate["rerank_score"] = score
        ranked.append(candidate)
    if debug_dir is not None:
        write_json(
            Path(debug_dir) / "knowledge_rerank.json",
            {
                "candidates": [_candidate_key(row) for row in candidates],
                "selected": [
                    {"candidate": _candidate_key(row), "score": row["rerank_score"]}
                    for row in ranked
                ],
            },
        )
    return ranked


# Only the best-matching cases carry a diff; the rest are corroboration.
_MAX_CASES_WITH_PATCH = 2
# A case's issue markdown is background, not the answer — cap it.
_MAX_ISSUE_CHARS = 1500
# Hard ceiling for one rendered bundle. The top entry is always kept whole, even
# if it alone exceeds this, because dropping the best match defeats retrieval.
_MAX_BUNDLE_CHARS = 18000


def _render_rank_line(row: dict[str, Any]) -> str:
    """Report the ranking basis honestly.

    ``rerank_score is None`` means the cross-encoder never ran (missing optional
    dependency, model load failure, or an inference error) and the ordering is
    just ts_rank. Saying so beats printing ``0.0000``, which reads as a real
    score and hides the degradation.
    """
    score = row.get("rerank_score")
    if score is None:
        return "Ranking: ts_rank order (cross-encoder unavailable)"
    return f"Cross-encoder score: {float(score):.4f}"


def _candidate_key(row: dict[str, Any]) -> str:
    if row.get("source_type") == "MIC-741 case":
        return str(row.get("case_key") or "unknown")
    return str(row.get("candidate_id") or row.get("doc_key") or "unknown")


def query_doc_knowledge(
    issue: str,
    logs: list[str],
    settings: "Settings",
    *,
    limit: int | None = None,
    debug_dir: str | Path | None = None,
) -> str:
    if not settings.mic741_knowledge_db_url:
        raise KnowledgeDBError("MIC741_KNOWLEDGE_DB_URL is not configured")
    query_text = "\n".join([issue, *logs]).strip()
    if not query_text:
        return _render_candidates([])
    fts_query = _fts_query_text_prefix(query_text)
    if not fts_query:
        return _render_candidates([])
    candidates = _query_doc_candidates(
        settings.mic741_knowledge_db_url,
        fts_query,
        limit=limit or settings.rerank_candidate_limit,
    )
    ranked = _rank_candidates(issue, candidates, settings, debug_dir=debug_dir)
    return _render_candidates(ranked)


def query_all_knowledge(
    issue: str,
    logs: list[str],
    settings: "Settings",
    *,
    debug_dir: str | Path | None = None,
) -> str:
    if not settings.mic741_knowledge_db_url:
        raise KnowledgeDBError("MIC741_KNOWLEDGE_DB_URL is not configured")
    query_text = "\n".join([issue, *logs]).strip()
    if not query_text:
        return _render_candidates([])
    fts_query = _fts_query_text_prefix(query_text)
    if not fts_query:
        return _render_candidates([])

    candidate_limit = max(settings.rerank_candidate_limit, 0)
    case_rows = _query_rows(
        settings.mic741_knowledge_db_url,
        fts_query,
        subsystem=None,
        limit=candidate_limit,
    )
    candidates = [_case_candidate(row) for row in case_rows]
    candidates.extend(
        _query_doc_candidates(
            settings.mic741_knowledge_db_url,
            fts_query,
            limit=candidate_limit,
        )
    )
    candidates = sorted(
        candidates,
        key=lambda row: float(row.get("rank") or 0.0),
        reverse=True,
    )[:candidate_limit]
    ranked = _rank_candidates(issue, candidates, settings, debug_dir=debug_dir)
    _attach_patch_excerpts(ranked, issue, logs, settings)
    return _render_candidates(ranked)


def _attach_patch_excerpts(
    ranked: list[dict[str, Any]],
    issue: str,
    logs: list[str],
    settings: "Settings",
) -> None:
    """Give a diff only to the best-matching cases.

    Every case used to carry a full patch excerpt, so a single bundle reached
    73k characters — three unrelated cases contributed 53k of it — and the
    answer drowned in a 62k-token context. Lower-ranked cases are corroboration:
    the agent needs to know they exist, not to read their diffs.
    """
    cases_with_patch = 0
    for row in ranked:
        patch_content = str(row.pop("patch_content", "") or "")
        if row.get("source_type") != "MIC-741 case":
            continue
        if cases_with_patch >= _MAX_CASES_WITH_PATCH:
            row["patch_excerpt"] = ""
            continue
        row["patch_excerpt"] = _select_relevant_hunks(
            patch_content,
            issue,
            logs,
            settings.mic741_knowledge_hunk_budget_chars,
        )
        cases_with_patch += 1


def _render_candidates(rows: list[dict[str, Any]]) -> str:
    """Render the ranked bundle under a hard total budget.

    Entries are dropped whole from the tail rather than cut mid-entry: a
    half-rendered diff is worse than an absent one, and the highest-ranked
    entries are the ones worth keeping. The budget exists because an unbounded
    bundle reached 73k characters and buried the answer.
    """
    heading = "## Reference Knowledge (docs / pinmux)"
    if not rows:
        return f"{heading}\n\nNo reference knowledge matched.\n"

    lines = [heading, ""]
    used = len(heading) + 1
    dropped = 0
    for index, row in enumerate(rows, start=1):
        source_type = str(row.get("source_type") or "document")
        if source_type == "MIC-741 case":
            entry = _render_case(index, row)
        else:
            entry = _render_document(index, row)
        size = sum(len(line) + 1 for line in entry)
        if index > 1 and used + size > _MAX_BUNDLE_CHARS:
            dropped = len(rows) - index + 1
            break
        lines.extend(entry)
        used += size
    if dropped:
        lines.append(f"({dropped} lower-ranked match(es) omitted to bound context size.)")
    return "\n".join(lines).rstrip() + "\n"


def _render_case(index: int, row: dict[str, Any]) -> list[str]:
    case_key = str(row.get("case_key") or "unknown")
    title = str(row.get("title") or case_key)
    lines = [
        f"### {index}. [MIC-741 case] {case_key} - {title}",
        f"Source: MIC-741 case `{case_key}`",
        f"Subsystem: {row.get('subsystem') or '(unknown)'}",
        f"Commit: {row.get('commit_sha') or '(unknown)'}",
        _render_rank_line(row),
        "",
        "Historical issue:",
        str(row.get("issue_markdown") or "(not available)")[:_MAX_ISSUE_CHARS],
        "",
        "Human fix:",
        str(row.get("solution_summary") or "(not extracted)"),
        "",
        "Repair rule:",
        str(row.get("repair_rule") or "(not extracted)"),
        "",
    ]
    patch_excerpt = str(row.get("patch_excerpt") or "").strip()
    if patch_excerpt:
        lines.extend(["Patch excerpt:", "```diff", patch_excerpt, "```", ""])
    return lines


def _render_document(index: int, row: dict[str, Any]) -> list[str]:
    source_type = str(row.get("source_type") or "document")
    title = str(row.get("title") or row.get("doc_key") or "untitled")
    lines = [
        f"### {index}. [{source_type}] {title}",
        f"Source: {source_type}",
        f"Document: {title} (`{row.get('doc_key') or 'unknown'}`)",
        f"Chunk type: {row.get('chunk_type') or '(unknown)'}",
        f"Platform: {row.get('platform') or '(unknown)'}",
        f"Version: {row.get('doc_version') or '(unknown)'}",
    ]
    if source_type == "pinmux pin":
        lines.extend(
            [
                f"Ball: {row.get('ball') or '(unknown)'}",
                f"Signal: {row.get('signal_name') or '(unknown)'}",
            ]
        )
    else:
        lines.extend(
            [
                f"Page: {row.get('page') or '(unknown)'}",
                f"Section: {row.get('section_path') or '(unknown)'}",
            ]
        )
    lines.extend(
        [
            _render_rank_line(row),
            "",
            str(row.get("content") or ""),
            "",
        ]
    )
    return lines
