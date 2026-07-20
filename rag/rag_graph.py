"""RAG CRAG subgraph — proper LangGraph StateGraph.

Flow:
    START
      → input_planner      (Block A: any input → Retrieval Query Object)
      → hybrid_retrieve    (Block B: Qdrant + PostgreSQL + Neo4j in parallel)
      → grader             (CRAG quality check via reranker score)
        ├─ good  ──────────→ llm → END
        ├─ retry ──────────→ rewrite → hybrid_retrieve  (loop)
        └─ gap   ──────────→ gap_report → llm → END

This replaces the plain Python for-loop in rag_integration.py so every node
appears in draw_mermaid() output and gets its own Langfuse span.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

_local_index_ready = False


def ensure_local_index(kb_dir=None) -> None:
    """Build or restore local KB index (idempotent, runs once per process).

    Args:
        kb_dir: explicit KB directory (Path); when called from the agent node
                this receives settings.mic741_knowledge_source_dir so both
                FTS and CRAG point at the same knowledge base.
    """
    global _local_index_ready
    if _local_index_ready:
        return
    from rag.indexer import build_index
    build_index(force=False, kb_dir=kb_dir)
    _local_index_ready = True

from rag.nodes.gap_report import gap_report_node
from rag.nodes.grader import grade_node
from rag.nodes.hybrid_retrieve import hybrid_retrieve_node
from rag.nodes.input_planner import input_planner_node
from rag.nodes.llm import llm_node
from rag.nodes.rewrite import rewrite_node
from rag.rag_state import AgentState
from rag.config import CRAG_MAX_RETRIES, CRAG_SCORE_THRESHOLD


def _route_after_grader(state: AgentState) -> Literal["llm", "rewrite", "gap_report"]:
    score = state.get("crag_score", 0.0)
    retry = state.get("retry_count", 0)
    if score >= CRAG_SCORE_THRESHOLD:
        return "llm"
    if retry < CRAG_MAX_RETRIES:
        return "rewrite"
    return "gap_report"


def build_rag_graph():
    """Build and compile the RAG CRAG subgraph."""
    graph = StateGraph(AgentState)

    graph.add_node("input_planner", input_planner_node)
    graph.add_node("hybrid_retrieve", hybrid_retrieve_node)
    graph.add_node("grader", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("gap_report", gap_report_node)
    graph.add_node("llm", llm_node)

    graph.add_edge(START, "input_planner")
    graph.add_edge("input_planner", "hybrid_retrieve")
    graph.add_edge("hybrid_retrieve", "grader")
    graph.add_conditional_edges(
        "grader",
        _route_after_grader,
        {"llm": "llm", "rewrite": "rewrite", "gap_report": "gap_report"},
    )
    graph.add_edge("rewrite", "hybrid_retrieve")
    graph.add_edge("gap_report", "llm")
    graph.add_edge("llm", END)

    return graph.compile()
