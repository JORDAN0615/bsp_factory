"""Block A — Input Planner node.

Single LLM call that converts any input format (natural language, test report,
code/log paste) into a structured Retrieval Query Object with 4 fields.
"""

from __future__ import annotations

import json
import re

from rag_config import LLM_CONFIG, NEO4J_ENTRY_NODES, DEBUG_RETRIEVAL, INPUT_PLANNER_USE_LLM
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
    """Enhanced rule-based query decomposition (default path, no LLM needed).

    Extracts BSP-relevant signals directly from structured error logs:
    - Error codes (numeric, hex, -ERRNO)
    - CamelCase / UPPER_CASE identifiers (driver names, components)
    - snake_case function/symbol names
    - Neo4j component hints from the known entry-node list
    """
    keywords: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = term.strip()
        if t and t not in seen and len(t) > 2:
            seen.add(t)
            keywords.append(t)

    # Error codes: -121, errno style, hex addresses
    for m in re.findall(r'(?:error|err|errno|code|ret|retval)[\s:=]+(-?\d+|0x[0-9a-fA-F]+)', raw_input, re.IGNORECASE):
        _add(m)
    for m in re.findall(r'\b0x[0-9a-fA-F]{4,}\b', raw_input):
        _add(m)
    # Standalone -NNN patterns common in kernel logs
    for m in re.findall(r'\s(-\d{1,4})\b', raw_input):
        _add(m)

    # UPPER_CASE identifiers and CamelCase words (driver names, components)
    for m in re.findall(r'\b[A-Z][A-Za-z0-9]{2,}\b|\b[A-Z]{2,}\b', raw_input):
        if m not in {'The', 'This', 'That', 'When', 'After', 'With', 'From', 'Boot', 'Into', 'Over'}:
            _add(m)

    # snake_case symbols (kernel function names, device tree nodes, file paths)
    for m in re.findall(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b', raw_input):
        _add(m)

    # Common BSP error phrases as bigrams
    for m in re.findall(r'(?:probe failed|link down|not detected|out of memory|timeout|dmesg|ifconfig|lsusb|i2c transfer|cannot open)', raw_input, re.IGNORECASE):
        _add(m)

    # Build concise semantic query: first 200 chars, whitespace-normalised
    semantic = re.sub(r'\s+', ' ', raw_input[:200]).strip()

    hints = [node for node in NEO4J_ENTRY_NODES
             if node.lower() in raw_input.lower()][:3]

    return {
        "semantic_query": semantic,
        "filters": {},
        "keywords": keywords[:18],
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

    query_object = None

    if INPUT_PLANNER_USE_LLM:
        # LLM path: slower (~30-60s reasoning model), better for ambiguous natural-language input
        node_list = ", ".join(f'"{n}"' for n in NEO4J_ENTRY_NODES)
        prompt = _PLANNER_PROMPT.format(raw_input=raw_input, node_list=node_list)
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
        # Rule-based path (default): instant, covers BSP structured error logs well
        query_object = _build_fallback(raw_input)
        if DEBUG_RETRIEVAL:
            mode = "rule-based (INPUT_PLANNER_USE_LLM=0)" if not INPUT_PLANNER_USE_LLM else "rule-based fallback (LLM failed)"
            print(f"\n[INPUT_PLANNER] using {mode}")

    if not query_object["semantic_query"]:
        query_object["semantic_query"] = raw_input[:300]

    if DEBUG_RETRIEVAL:
        print(f"\n[INPUT_PLANNER] query_object={json.dumps(query_object, ensure_ascii=False, indent=2)}\n")

    return {
        "query_object": query_object,
        "query_history": state.get("query_history", []) + [query_object],
    }

