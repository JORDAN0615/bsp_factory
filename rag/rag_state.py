"""AgentState for LangGraph BSP Agent."""

from __future__ import annotations

from typing import Literal, TypedDict

from rag.models import Chunk


class AgentState(TypedDict, total=False):
    # ── Block A: input ────────────────────────────────────────────
    original_input: str
    route: Literal["chat", "kb"]   # "kb" when called from agent; "chat" for standalone
    query_object: dict             # {semantic_query, filters, keywords, graph_hints}

    # ── Block B/C: retrieval ──────────────────────────────────────
    candidates: list[Chunk]
    reranked_results: list[Chunk]  # Chunk.score populated after reranker

    # ── Block 6: CRAG ─────────────────────────────────────────────
    crag_score: float
    retry_count: int
    query_history: list[dict]    # query_objects tried so far
    crag_history: list[float]    # crag_scores per attempt

    # ── Block 7: generation ───────────────────────────────────────
    llm_answer: str
    citations: list[str]

    # ── Block 8: feedback ─────────────────────────────────────────
    verify_status: Literal["success", "failure", "gap"]
    feedback_recorded: bool

    # ── Gap report ────────────────────────────────────────────────
    gap_report: dict

    # ── Subgraph output (merged back to RepairGraphState) ─────────
    # Formatted KB answer injected into patch_agent prompt.
    # Key name matches RepairGraphState.rag_context so LangGraph
    # merges it automatically when RAG runs as a subgraph node.
    rag_context: str


BSPState = AgentState
