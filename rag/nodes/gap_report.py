"""Gap Report node — triggered when CRAG exhausts retries without good results.

Records a Knowledge Gap entry into PostgreSQL review_queue (if available),
and returns a user-facing message.
"""

from __future__ import annotations

import json
from datetime import datetime

from rag.config import DEBUG_RETRIEVAL
from rag.rag_state import AgentState


def gap_report_node(state: AgentState) -> dict:
    original_input = state.get("original_input", "")
    query_history  = state.get("query_history", [])
    crag_history   = state.get("crag_history", [])

    report = {
        "type": "knowledge_gap",
        "original_input": original_input,
        "query_attempts": [
            {"query_object": qo, "crag_score": score}
            for qo, score in zip(query_history, crag_history)
        ],
        "best_score_achieved": max(crag_history) if crag_history else 0.0,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
    }

    # Write to PostgreSQL review_queue if available
    try:
        from db.postgres import insert_gap_report, is_available
        if is_available():
            insert_gap_report(report)
            if DEBUG_RETRIEVAL:
                print("[GAP_REPORT] written to review_queue")
    except Exception as e:
        if DEBUG_RETRIEVAL:
            print(f"[GAP_REPORT] DB write skipped: {e}")

    if DEBUG_RETRIEVAL:
        print(f"\n[GAP_REPORT] best_score={report['best_score_achieved']:.3f} "
              f"attempts={len(query_history)}\n")

    return {
        "gap_report":    report,
        "verify_status": "gap",
    }

