"""Knowledge context formatter node.

KB path  — formats retrieved chunks as structured English markdown (no LLM call).
           Raw chunk content is preserved so patch_agent receives the full source text.
Gap path — emits a brief note when no KB record matched; patch_agent falls back to
           code inspection.
Chat path — standalone mode only; uses LLM, rag_context is not forwarded to agent.
"""

from __future__ import annotations

from rag.config import DEBUG_RETRIEVAL, LLM_CONFIG, LLM_TOP_K_CHUNKS, LLM_CHUNK_MAX_CHARS
from rag.rag_state import AgentState

_CHAT_SYSTEM = (
    "You are a helpful assistant for Advantech MIC BSP engineers. "
    "Respond briefly and in Traditional Chinese."
)


def _format_chunks_as_context(chunks, top_k: int, max_chars: int) -> str:
    """Render reranked chunks as structured English markdown for patch_agent context.

    No LLM synthesis — content is passed through verbatim so the downstream agent
    sees the full retrieved text rather than a distilled summary.
    """
    if not chunks:
        return ""
    blocks: list[str] = ["## CRAG Knowledge Context", ""]
    for i, chunk in enumerate(chunks[:top_k], 1):
        source = getattr(chunk, "source", "unknown")
        section = getattr(chunk, "section", "")
        score = getattr(chunk, "score", 0.0)

        header = f"### [{i}] {source}"
        if section:
            header += f" / {section}"
        blocks.append(header)
        blocks.append(f"Relevance score: {score:.3f}")
        blocks.append("")

        text = chunk.text[:max_chars]
        if len(chunk.text) > max_chars:
            text += "\n... (truncated)"
        blocks.append(text)
        blocks.append("")
        if i < min(len(chunks), top_k):
            blocks.append("---")
            blocks.append("")

    return "\n".join(blocks).rstrip() + "\n"



def llm_node(state: AgentState) -> dict:
    original_input = state.get("original_input", "")
    route = state.get("route") or "kb"
    verify_status = state.get("verify_status", "")

    # ── Chat path: standalone mode, rag_context not forwarded to agent ───────
    if route == "chat":
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                **{k: v for k, v in LLM_CONFIG.items() if v and k != "temperature"},
                temperature=0,
            )
            result = llm.invoke([
                {"role": "system", "content": _CHAT_SYSTEM},
                {"role": "user", "content": original_input},
            ])
            answer = str(result.content)
        except Exception as e:
            answer = f"LLM call failed: {e}"
        return {"llm_answer": answer, "citations": [], "rag_context": ""}

    # ── Gap path: KB exhausted, return empty so knowledge_context is unchanged ─
    if verify_status == "gap":
        if DEBUG_RETRIEVAL:
            gap_report = state.get("gap_report", {})
            best = gap_report.get("best_score_achieved", 0.0)
            attempts = len(gap_report.get("query_attempts", []))
            print(f"\n[LLM node] GAP — {attempts} attempt(s), best score {best:.3f} → no output")
        return {"llm_answer": "", "citations": [], "rag_context": ""}

    # ── KB path: format chunks directly, no LLM synthesis ───────────────────
    chunks = state.get("reranked_results", state.get("candidates", []))
    if DEBUG_RETRIEVAL:
        n = len(chunks) if chunks else 0
        print(f"\n[LLM node] KB — formatting {n} chunks (no LLM synthesis)")

    rag_context = _format_chunks_as_context(chunks, LLM_TOP_K_CHUNKS, LLM_CHUNK_MAX_CHARS)
    return {"llm_answer": "", "citations": [], "rag_context": rag_context}

