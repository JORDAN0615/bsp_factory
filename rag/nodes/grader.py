"""CRAG grade node — decides pass/retry/gap based on reranker score.

Uses the top-1 reranker score already in state (computed in hybrid_retrieve_node).
No extra LLM call needed.

  score >= CRAG_SCORE_THRESHOLD → "good"
  score <  threshold, retry < max → "retry"
  retry >= max → "gap"
"""

from __future__ import annotations

from rag.config import CRAG_SCORE_THRESHOLD, CRAG_MAX_RETRIES, DEBUG_RETRIEVAL
from rag.rag_state import AgentState


def grade_node(state: AgentState) -> dict:
    score = state.get("crag_score", 0.0)
    retry = state.get("retry_count", 0)

    crag_history = state.get("crag_history", []) + [score]

    if score >= CRAG_SCORE_THRESHOLD:
        verdict = "good"
    elif retry < CRAG_MAX_RETRIES:
        verdict = "retry"
    else:
        verdict = "gap"

    if DEBUG_RETRIEVAL:
        print(f"\n[GRADER] score={score:.3f} threshold={CRAG_SCORE_THRESHOLD} "
              f"retry={retry}/{CRAG_MAX_RETRIES} → {verdict}\n")

    return {
        "crag_history": crag_history,
        "verify_status": "success" if verdict == "good" else "gap",
    }

