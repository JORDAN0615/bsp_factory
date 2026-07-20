"""CRAG rewrite node — context-aware query rewriting.

Strategy A (retry == 1): Relax filters — drop model/version constraints so
  the search casts a wider net.
Strategy B (retry == 2): Semantic expand — ask LLM to rephrase using synonyms
  and broader BSP terminology, informed by query_history and crag_history.
"""

from __future__ import annotations

import json

from rag.config import LLM_CONFIG, DEBUG_RETRIEVAL
from rag.rag_state import AgentState


def _strategy_a(query_object: dict) -> dict:
    """Drop restrictive metadata filters to broaden recall."""
    new_qo = dict(query_object)
    new_qo["filters"] = {}
    return new_qo


def _strategy_b_prompt(original_input: str, query_history: list[dict], crag_history: list[float]) -> str:
    hist_lines = []
    for i, (qo, score) in enumerate(zip(query_history, crag_history), 1):
        hist_lines.append(f"  attempt {i}: semantic_query={qo.get('semantic_query','')!r}  score={score:.3f}")
    history_text = "\n".join(hist_lines) if hist_lines else "  (none)"
    return f"""\
You are a BSP retrieval query optimizer.
The original user input: {original_input!r}

Previous attempts and their reranker scores (0=poor, 1=perfect):
{history_text}

The retrieval quality was insufficient. Produce a new Retrieval Query Object
with a rephrased semantic_query using different BSP terminology, synonyms,
and broader scope. Keep useful keywords from prior attempts.

Output strict JSON only:
{{
  "semantic_query": "...",
  "filters": {{}},
  "keywords": [],
  "graph_hints": []
}}"""


def rewrite_node(state: AgentState) -> dict:
    retry = state.get("retry_count", 0)
    query_object = state.get("query_object", {})
    query_history = state.get("query_history", [])
    crag_history = state.get("crag_history", [])
    original_input = state.get("original_input", "")

    new_qo = None

    if retry == 0 and query_object.get("filters"):
        # Strategy A: relax filters (only useful when filters exist)
        new_qo = _strategy_a(query_object)
        if DEBUG_RETRIEVAL:
            print(f"\n[REWRITE] Strategy A (relax filters): {json.dumps(new_qo, ensure_ascii=False)}\n")
    else:
        # Strategy B: LLM semantic expand
        prompt = _strategy_b_prompt(original_input, query_history, crag_history)
        try:
            from langchain_openai import ChatOpenAI
            import re

            llm = ChatOpenAI(
                **{k: v for k, v in LLM_CONFIG.items() if v and k != "temperature"},
                temperature=0.4,
                max_retries=1,
            )
            result = llm.invoke([{"role": "user", "content": prompt}])
            raw = re.sub(r'<think>[\s\S]*?</think>', '', str(result.content), flags=re.IGNORECASE).strip()
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                import json as _json
                new_qo = _json.loads(match.group())
        except Exception as e:
            if DEBUG_RETRIEVAL:
                print(f"\n[REWRITE] Strategy B LLM failed: {e}")

        if new_qo is None:
            # Fallback: expand with BSP keywords
            sq = query_object.get("semantic_query", original_input)
            new_qo = {
                "semantic_query": f"BSP driver debug troubleshoot {sq}",
                "filters": {},
                "keywords": query_object.get("keywords", []),
                "graph_hints": query_object.get("graph_hints", []),
            }
        if DEBUG_RETRIEVAL:
            print(f"\n[REWRITE] Strategy B (semantic expand): {json.dumps(new_qo, ensure_ascii=False)}\n")

    new_retry = retry + 1
    new_history = query_history + [new_qo]

    return {
        "query_object": new_qo,
        "retry_count": new_retry,
        "query_history": new_history,
    }

