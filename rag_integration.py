"""RAG integration adapter for bsp_factory.

Flow when KB_API_URL is set (production):
  input_planner → KBClient.query() → rerank → CRAG grade → LLM / gap

Flow when KB_API_URL is not set (local testing):
  input_planner → local Qdrant+BM25 CRAG loop → LLM / gap
  (indexes MIC-741_KnowledgeBase/ automatically on first call)

Set KB_API_URL in .env to switch to the server KB.
Set KB_DIR in .env to change the local KB directory (default: MIC-741_KnowledgeBase).
"""

from __future__ import annotations

from typing import TypedDict


class RAGResult(TypedDict):
    answer: str
    citations: list[str]
    crag_score: float
    source: str          # "kb" | "gap" — whether KB had relevant records


_local_index_ready = False


def _ensure_local_index() -> None:
    """Build or restore local KB index (runs once per process)."""
    global _local_index_ready
    if _local_index_ready:
        return
    from rag.indexer import build_index
    build_index(force=False)  # build_index handles cache/Qdrant checks internally
    _local_index_ready = True


def query_rag(issue: str, error_signatures: list[str] | None = None) -> RAGResult:
    """Query the KB and return a structured answer for patch_agent.

    Uses remote KB (KB_API_URL) when configured, otherwise falls back to the
    local index built from MIC-741_KnowledgeBase/ (or KB_DIR env var).
    """
    from rag_config import CRAG_SCORE_THRESHOLD, CRAG_MAX_RETRIES
    from rag.nodes.input_planner import input_planner_node
    from rag.nodes.llm import llm_node
    from rag.nodes.gap_report import gap_report_node
    from kb_client import KBClient

    # Build enriched query: issue + error signatures
    enriched_input = issue
    if error_signatures:
        enriched_input = issue + "\n\nError signatures: " + ", ".join(error_signatures)

    # ── Step 1: Input Planner — extract semantic_query from natural language ──
    planner_state: dict = {
        "original_input": enriched_input,
        "route": "kb",
        "query_history": [],
    }
    planner_state.update(input_planner_node(planner_state))
    query_object = planner_state.get("query_object", {})
    semantic_query = query_object.get("semantic_query") or enriched_input

    # ── Step 2: Retrieve + CRAG ──────────────────────────────────────────────
    kb = KBClient()

    if kb.available:
        # Remote mode: single query to server KB, rerank locally
        from rag.reranker import rerank
        from rag.models import Chunk

        kb_chunks = kb.query(semantic_query, top_k=20)
        rag_chunks = [
            Chunk(id=c.id, text=c.text, source=c.source, section=c.section)
            for c in kb_chunks
        ]
        reranked = rerank(semantic_query, rag_chunks, top_k=5)
        crag_score = reranked[0].score if reranked else 0.0
        final_verdict = "good" if crag_score >= CRAG_SCORE_THRESHOLD else "gap"

        llm_state: dict = {
            "original_input": enriched_input,
            "route": "kb",
            "reranked_results": reranked,
            "candidates": reranked,
            "crag_score": crag_score,
            "verify_status": "gap" if final_verdict == "gap" else "success",
            "query_history": [query_object],
            "crag_history": [crag_score],
            "gap_report": {
                "query_attempts": [{"query_object": query_object, "crag_score": crag_score}],
                "best_score_achieved": crag_score,
            },
        }
    else:
        # Local mode: full CRAG loop against local Qdrant + BM25 index
        _ensure_local_index()

        from rag.nodes.hybrid_retrieve import hybrid_retrieve_node
        from rag.nodes.grader import grade_node
        from rag.nodes.rewrite import rewrite_node

        state: dict = {
            "original_input": enriched_input,
            "route": "kb",
            "query_object": query_object,
            "query_history": [query_object],
            "crag_history": [],
            "retry_count": 0,
        }

        final_verdict = "gap"
        for _ in range(CRAG_MAX_RETRIES + 1):
            state.update(hybrid_retrieve_node(state))
            state.update(grade_node(state))

            crag_score = state.get("crag_score", 0.0)
            if crag_score >= CRAG_SCORE_THRESHOLD:
                final_verdict = "good"
                break
            if state.get("retry_count", 0) >= CRAG_MAX_RETRIES:
                break
            state.update(rewrite_node(state))

        llm_state = state

    # ── Step 3: LLM answer ───────────────────────────────────────────────────
    if final_verdict == "gap":
        llm_state.update(gap_report_node(llm_state))

    llm_state.update(llm_node(llm_state))

    return RAGResult(
        answer=llm_state.get("llm_answer", ""),
        citations=llm_state.get("citations", []),
        crag_score=llm_state.get("crag_score", 0.0),
        source="gap" if final_verdict == "gap" else "kb",
    )
