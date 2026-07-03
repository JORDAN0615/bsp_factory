"""Guard node — LLM-based chat/kb routing.

Single constrained LLM call: outputs only "chat" or "kb".
Falls back to "kb" on any failure so technical questions are never dropped.
"""

from __future__ import annotations

from rag_config import LLM_CONFIG
from rag.rag_state import AgentState

_SYSTEM = (
    "You are a router for an Advantech MIC BSP engineering assistant.\n\n"
    "Decide whether the user is seeking technical assistance.\n\n"
    "Reply \"kb\" if the user needs technical help — searching a BSP knowledge base "
    "would benefit them.\n"
    "Reply \"chat\" if the user does not need technical help — they are just talking.\n\n"
    "Reply with ONLY the single word: chat or kb"
)


def guard_node(state: AgentState) -> dict:
    user_input = state["original_input"].strip()

    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            **{k: v for k, v in LLM_CONFIG.items() if v and k != "temperature"},
            temperature=0,
            max_tokens=512,
        )
        result = llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_input},
        ])
        # Strip <think>...</think> block if present (Qwen3 thinking mode)
        content = str(result.content).strip()
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        route = "chat" if "chat" in content.lower() else "kb"
    except Exception:
        route = "kb"

    return {"route": route}

