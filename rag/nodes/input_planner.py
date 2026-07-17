"""Block A — Input Planner node.

Single LLM call that converts any input format (natural language, test report,
code/log paste) into a structured Retrieval Query Object with 4 fields.
"""

from __future__ import annotations

import json
import re

from rag_config import LLM_CONFIG, NEO4J_ENTRY_NODES, DEBUG_RETRIEVAL
from rag.rag_state import AgentState

_PLANNER_SYSTEM = "You are a BSP retrieval query planner. Output strict JSON only, no markdown fences."

_PLANNER_PROMPT = """\
Convert the BSP input below into a Retrieval Query Object.
No information should be lost — distribute it across the four fields:

Neo4j entry nodes you MAY reference in graph_hints (pick ONLY from this list):
{node_list}

Field rules:
- semantic_query: 3-8 keyword-dense technical terms for vector search. NOT a full sentence.
  Focus on the core hardware/driver/error concept. Drop conversational filler.
- keywords: ALL specific technical terms from input — symptoms, error descriptions, driver names,
  error codes, kernel messages, function names, file paths, hex addresses.
- filters: dict with ONLY keys explicitly stated: model, bsp_version, status. Empty {{}} if not mentioned.
- graph_hints: pick ONLY names from the Neo4j entry node list that are clearly relevant.

Example:
  Input: "今天在測試的時候有遇到 usb 的 driver issue, 我的 usb 裝置接到機台的 usb port 都沒有反應"
  Output:
  {{
    "semantic_query": "USB device no response driver failure",
    "filters": {{}},
    "keywords": ["USB", "driver issue", "no response", "port", "device not detected"],
    "graph_hints": ["USB"]
  }}

Input:
{raw_input}

Output (strict JSON only):
{{
  "semantic_query": "...",
  "filters": {{}},
  "keywords": [],
  "graph_hints": []
}}"""

_FALLBACK_QUERY = {
    "semantic_query": "",
    "filters": {},
    "keywords": [],
    "graph_hints": [],
}


def _build_fallback(raw_input: str) -> dict:
    """Rule-based fallback when LLM is unavailable."""
    words = raw_input.split()
    keywords = [w for w in words if len(w) > 4 and not w.islower()][:10]
    hints = [node for node in NEO4J_ENTRY_NODES
             if node.lower() in raw_input.lower()][:3]
    return {
        "semantic_query": raw_input[:300],
        "filters": {},
        "keywords": keywords,
        "graph_hints": hints,
    }


def _strip_thinking(raw: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (e.g. minimax, deepseek-r1)."""
    return re.sub(r'<think>[\s\S]*?</think>', '', raw, flags=re.IGNORECASE).strip()


def _parse_query_object(raw: str) -> dict | None:
    """Extract and validate JSON from LLM output."""
    raw = _strip_thinking(raw)
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return None
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    required = {"semantic_query", "filters", "keywords", "graph_hints"}
    if not required.issubset(obj.keys()):
        return None
    if not isinstance(obj["keywords"], list):
        obj["keywords"] = []
    if not isinstance(obj["graph_hints"], list):
        obj["graph_hints"] = []
    if not isinstance(obj["filters"], dict):
        obj["filters"] = {}

    # Guard: graph_hints must only contain nodes from our list
    valid_nodes = set(NEO4J_ENTRY_NODES)
    obj["graph_hints"] = [h for h in obj["graph_hints"] if h in valid_nodes]
    return obj


def input_planner_node(state: AgentState) -> dict:
    raw_input = state["original_input"]
    node_list = ", ".join(f'"{n}"' for n in NEO4J_ENTRY_NODES)
    prompt = _PLANNER_PROMPT.format(raw_input=raw_input, node_list=node_list)

    query_object = None
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            **{k: v for k, v in LLM_CONFIG.items() if v and k != "temperature"},
            temperature=0,
            max_retries=1,
        )
        result = llm.invoke([
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        query_object = _parse_query_object(str(result.content))
    except Exception as e:
        if DEBUG_RETRIEVAL:
            print(f"\n[INPUT_PLANNER] LLM call failed: {e}")

    if query_object is None:
        query_object = _build_fallback(raw_input)
        if DEBUG_RETRIEVAL:
            print("\n[INPUT_PLANNER] using rule-based fallback")

    if not query_object["semantic_query"]:
        query_object["semantic_query"] = raw_input[:300]

    if DEBUG_RETRIEVAL:
        print(f"\n[INPUT_PLANNER] query_object={json.dumps(query_object, ensure_ascii=False, indent=2)}\n")

    return {
        "query_object": query_object,
        "query_history": state.get("query_history", []) + [query_object],
    }

