"""LLM answer generation node — structured output for KB path, conversational for chat."""

from __future__ import annotations

import json
import re

from rag_config import DEBUG_RETRIEVAL, LLM_CONFIG
from rag.rag_state import AgentState


_SYSTEM = (
    "You are MIC BSP debug assistant for Advantech embedded systems (Jetson Thor / MIC-741). "
    "You have access to retrieved KB records (past verified fixes) AND your own deep knowledge "
    "of BSP development, Linux kernel, Device Tree, and NVIDIA Jetson platforms. "
    "Always attempt to diagnose and fix the problem. "
    "Use KB records as the primary reference when available; "
    "supplement with general BSP/kernel knowledge when KB is insufficient. "
    "Never refuse to answer — always provide actionable steps."
)

_KB_PROMPT = """\
Context (retrieved BSP knowledge — use as primary reference):
{context}

User Question:
{question}

Output a JSON object with these fields:
{{
  "root_cause": "根本原因說明",
  "fix_steps": ["步驟 1", "步驟 2", ...],
  "citations": ["source1", "source2", ...],
  "confidence": "verified|inferred"
}}

Rules:
- Use Traditional Chinese (繁體中文) for root_cause and fix_steps
- citations must match the [N] source labels in Context (empty [] if none used)
- confidence = "verified" if fix is directly from KB records; "inferred" if derived from general knowledge
- If Context is insufficient, apply your BSP/kernel knowledge to suggest the most likely fix
- Always output actionable fix_steps — never leave it empty unless truly impossible
- Output strict JSON only
"""

_GAP_SYSTEM = (
    "You are MIC BSP debug assistant for Advantech embedded systems. "
    "The internal knowledge base has no verified records for this question. "
    "Answer based on your general BSP / Linux kernel / embedded systems knowledge. "
    "Be accurate and practical, but always clarify this answer is inferred from general knowledge "
    "and has not been verified against internal records. "
    "Respond in Traditional Chinese."
)

_GAP_PROMPT = """\
【注意】內部知識庫已搜尋 {attempts} 次，未找到相關記錄（最高相似度 {best_score:.2f}）。
請根據你對 BSP / Linux kernel / 嵌入式系統的通用知識回答以下問題。

問題：
{question}

Output a JSON object with these fields:
{{
  "root_cause": "根據通用 BSP 知識推斷的根本原因",
  "fix_steps": ["步驟 1", "步驟 2", ...],
  "citations": []
}}

Rules:
- Use Traditional Chinese (繁體中文) for root_cause and fix_steps
- citations must be empty [] — no KB records were found
- Output strict JSON only
"""

_CHAT_SYSTEM = (
    "You are a helpful assistant for Advantech MIC BSP engineers. "
    "Respond briefly and in Traditional Chinese."
)


def _format_context(chunks) -> str:
    blocks = []
    for i, chunk in enumerate(chunks, 1):
        source = getattr(chunk, "source", "unknown")
        section = getattr(chunk, "section", "")
        score = getattr(chunk, "score", 0.0)
        label = f"[{i}] {source}"
        if section:
            label += f"/{section}"
        label += f" (score={score:.2f})"
        blocks.append(f"{label}\n{chunk.text}")
    return "\n\n---\n\n".join(blocks)


def _parse_kb_answer(raw: str) -> tuple[str, list[str]]:
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        try:
            obj = json.loads(match.group())
            root_cause = obj.get("root_cause", "")
            fix_steps = obj.get("fix_steps", [])
            citations = obj.get("citations", [])
            confidence = obj.get("confidence", "")
            lines = [f"**根本原因：** {root_cause}"]
            if fix_steps:
                lines.append("\n**修復步驟：**")
                for i, step in enumerate(fix_steps, 1):
                    lines.append(f"{i}. {step}")
            if confidence == "inferred":
                lines.append("\n> ⚠️ 以上為根據通用 BSP/Kernel 知識推斷，非 KB 驗證案例。")
            return "\n".join(lines), citations
        except (json.JSONDecodeError, AttributeError):
            pass
    return raw, []


def _format_rag_context(answer: str, citations: list[str], is_gap: bool) -> str:
    """Format the LLM answer into the rag_context block injected into patch_agent."""
    source_label = "（LLM 推斷，知識庫無記錄）" if is_gap else "（知識庫）"
    text = f"## BSP Knowledge Base Context {source_label}\n\n{answer}\n"
    if citations:
        text += "\n**來源：** " + ", ".join(citations) + "\n"
    return text


def llm_node(state: AgentState) -> dict:
    original_input = state.get("original_input", "")
    route = state.get("route") or "kb"
    verify_status = state.get("verify_status", "")

    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            **{k: v for k, v in LLM_CONFIG.items() if v and k != "temperature"},
            temperature=0,
        )
    except Exception as e:
        return {"llm_answer": f"LLM 初始化失敗: {e}", "citations": [], "rag_context": ""}

    # Chat path (standalone mode — rag_context not used by agent)
    if route == "chat":
        try:
            result = llm.invoke([
                {"role": "system", "content": _CHAT_SYSTEM},
                {"role": "user", "content": original_input},
            ])
            answer = str(result.content)
        except Exception as e:
            answer = f"LLM 呼叫失敗: {e}"
        return {"llm_answer": answer, "citations": [], "rag_context": ""}

    # Gap path: KB exhausted, LLM answers from own knowledge
    if verify_status == "gap":
        gap_report = state.get("gap_report", {})
        attempts = len(gap_report.get("query_attempts", []))
        best_score = gap_report.get("best_score_achieved", 0.0)
        prompt = _GAP_PROMPT.format(
            question=original_input,
            attempts=attempts,
            best_score=best_score,
        )
        if DEBUG_RETRIEVAL:
            print("\n" + "=" * 60)
            print("LLM PROMPT (GAP — no KB context)")
            print("=" * 60)
            print(prompt)
            print("=" * 60 + "\n")
        try:
            result = llm.invoke([
                {"role": "system", "content": _GAP_SYSTEM},
                {"role": "user", "content": prompt},
            ])
            raw = str(result.content)
        except Exception as e:
            raw = f"LLM 呼叫失敗: {e}"
        answer, _ = _parse_kb_answer(raw)
        answer = "⚠️ 知識庫無相關記錄，以下為 LLM 根據通用 BSP 知識推斷（未經內部資料驗證）：\n\n" + answer
        return {
            "llm_answer": answer,
            "citations": [],
            "rag_context": _format_rag_context(answer, [], is_gap=True),
        }

    # KB path: answer from retrieved context
    chunks = state.get("reranked_results", state.get("candidates", []))
    context = _format_context(chunks) if chunks else "(知識庫中沒有相關資料)"
    prompt = _KB_PROMPT.format(context=context, question=original_input)

    if DEBUG_RETRIEVAL:
        print("\n" + "=" * 60)
        print("LLM PROMPT (KB)")
        print("=" * 60)
        print(prompt[:1200] + ("..." if len(prompt) > 1200 else ""))
        print("=" * 60 + "\n")

    try:
        result = llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ])
        raw = str(result.content)
    except Exception as e:
        raw = f"LLM 呼叫失敗: {e}"

    answer, citations = _parse_kb_answer(raw)
    return {
        "llm_answer": answer,
        "citations": citations,
        "rag_context": _format_rag_context(answer, citations, is_gap=False),
    }

