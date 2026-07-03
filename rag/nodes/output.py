"""Output node — prints final answer to console."""

from __future__ import annotations

from rag.rag_state import AgentState


def output_node(state: AgentState) -> dict:
    answer = state.get("llm_answer", "(no answer)")
    citations = state.get("citations", [])
    verify_status = state.get("verify_status", "")

    print("\n" + "=" * 60)
    print("ANSWER")
    print("=" * 60)
    print(answer)
    if citations:
        print("\n來源：" + ", ".join(citations))
    if verify_status == "gap":
        print("\n[⚠] 知識缺口已記錄，等待審查")
    print("=" * 60 + "\n")
    return {}

