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
    from kb_client import KBClient

    enriched_input = issue
    if error_signatures:
        enriched_input = issue + "\n\nError signatures: " + ", ".join(error_signatures)

    kb = KBClient()

    if kb.available:
        return _query_remote(enriched_input, kb)
    else:
        return _query_local(enriched_input)


def _query_local(enriched_input: str) -> RAGResult:
    """Local mode: full CRAG loop via the RAG LangGraph subgraph."""
    _ensure_local_index()

    from rag.rag_graph import build_rag_graph

    result = build_rag_graph().invoke({
        "original_input": enriched_input,
        "route": "kb",
        "query_history": [],
        "crag_history": [],
        "retry_count": 0,
    })
    return RAGResult(
        answer=result.get("llm_answer", ""),
        citations=result.get("citations", []),
        crag_score=result.get("crag_score", 0.0),
        source="gap" if result.get("verify_status") == "gap" else "kb",
    )


def _query_remote(enriched_input: str, kb) -> RAGResult:
    """Remote mode: single query to server KB, rerank + grade + LLM locally."""
    from rag_config import CRAG_SCORE_THRESHOLD
    from rag.nodes.input_planner import input_planner_node
    from rag.nodes.gap_report import gap_report_node
    from rag.nodes.llm import llm_node
    from rag.reranker import rerank
    from rag.models import Chunk

    planner_state: dict = {"original_input": enriched_input, "route": "kb", "query_history": []}
    planner_state.update(input_planner_node(planner_state))
    query_object = planner_state.get("query_object", {})
    semantic_query = query_object.get("semantic_query") or enriched_input

    kb_chunks = kb.query(semantic_query, top_k=20)
    rag_chunks = [Chunk(id=c.id, text=c.text, source=c.source, section=c.section) for c in kb_chunks]
    reranked = rerank(semantic_query, rag_chunks, top_k=5)
    crag_score = reranked[0].score if reranked else 0.0
    is_gap = crag_score < CRAG_SCORE_THRESHOLD

    llm_state: dict = {
        "original_input": enriched_input,
        "route": "kb",
        "reranked_results": reranked,
        "candidates": reranked,
        "crag_score": crag_score,
        "verify_status": "gap" if is_gap else "success",
        "query_history": [query_object],
        "crag_history": [crag_score],
        "gap_report": {
            "query_attempts": [{"query_object": query_object, "crag_score": crag_score}],
            "best_score_achieved": crag_score,
        },
    }
    if is_gap:
        llm_state.update(gap_report_node(llm_state))
    llm_state.update(llm_node(llm_state))

    return RAGResult(
        answer=llm_state.get("llm_answer", ""),
        citations=llm_state.get("citations", []),
        crag_score=crag_score,
        source="gap" if is_gap else "kb",
    )
