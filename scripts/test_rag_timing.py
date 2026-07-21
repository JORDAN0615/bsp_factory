"""
RAG CRAG 直接計時測試
=====================
直接呼叫 rag.rag_graph，完全不經過 agent.graph，
記錄每個節點的耗時與輸出，供效能分析使用。

執行方式：
    python scripts/test_rag_timing.py
"""
from __future__ import annotations

import time
import sys
import os
from pathlib import Path

# 確保從 bsp_factory/ 根目錄執行
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ── 測試案例 ─────────────────────────────────────────────────────────
TEST_CASES = [
    {
        "name": "MGBE Ethernet 首次開機無法連線",
        "input": (
            "MGBE failed up connection automatically when 1st boot to desktop. "
            "The ethernet link stays down after BSP flashed. "
            "ifconfig shows mgbe0_0 is down. Manual restart fixes it."
        ),
        "expect_keywords": ["MGBE", "ethernet", "link down", "ifconfig"],
    },
    {
        "name": "Camera i2c -121 probe failed",
        "input": (
            "Camera probe failed with i2c -121 error. "
            "dmesg shows: imx390 0-001b: probe failed -121. "
            "i2c transfer timed out on camera CSI bus."
        ),
        "expect_keywords": ["i2c", "imx390", "probe", "camera"],
    },
    {
        "name": "USB 熱插拔無法偵測",
        "input": (
            "USB device not detected after hot-plug. "
            "lsusb shows nothing, dmesg shows usb 1-1: USB disconnect."
        ),
        "expect_keywords": ["USB", "disconnect", "lsusb"],
    },
]

# ── 節點計時 patch ───────────────────────────────────────────────────
_node_timings: list[dict] = []

def _timed_node(name: str, fn):
    """包裝節點函式，記錄執行時間與關鍵輸出欄位。"""
    def wrapper(state):
        t0 = time.perf_counter()
        print(f"\n{'─'*55}")
        print(f"  ▶ [{name}] 開始  ({time.strftime('%H:%M:%S')})")
        result = fn(state)
        elapsed = time.perf_counter() - t0

        # 收集有意義的摘要資訊
        summary_parts = []
        merged = {**state, **(result or {})}
        if "query_object" in merged:
            qo = merged["query_object"]
            summary_parts.append(f"semantic_query={qo.get('semantic_query','')!r:.60}")
            kw = qo.get("keywords", [])
            summary_parts.append(f"keywords({len(kw)})={kw[:4]}")
            summary_parts.append(f"graph_hints={qo.get('graph_hints', [])}")
        if "crag_score" in merged:
            summary_parts.append(f"crag_score={merged['crag_score']:.3f}")
        if "reranked_results" in merged:
            rr = merged["reranked_results"]
            summary_parts.append(f"reranked={len(rr)} chunks, top={rr[0].score:.3f}" if rr else "reranked=0")
        if "verify_status" in merged:
            summary_parts.append(f"verify_status={merged['verify_status']!r}")
        if "rag_context" in merged and merged["rag_context"]:
            ctx = merged["rag_context"]
            summary_parts.append(f"rag_context={len(ctx)} chars")

        print(f"  ✓ [{name}] 完成  耗時 {elapsed:.2f}s")
        for part in summary_parts:
            print(f"      {part}")

        _node_timings.append({"node": name, "elapsed": elapsed})
        return result
    return wrapper


def _patch_rag_graph():
    """在 rag_graph 的 node 函式上套計時包裝，必須在 build_rag_graph 之前呼叫。"""
    import rag.nodes.input_planner as ip_mod
    import rag.nodes.hybrid_retrieve as hr_mod
    import rag.nodes.grader as gr_mod
    import rag.nodes.rewrite as rw_mod
    import rag.nodes.gap_report as gap_mod
    import rag.nodes.llm as llm_mod

    ip_mod.input_planner_node   = _timed_node("input_planner",   ip_mod.input_planner_node)
    hr_mod.hybrid_retrieve_node = _timed_node("hybrid_retrieve", hr_mod.hybrid_retrieve_node)
    gr_mod.grade_node           = _timed_node("grader",          gr_mod.grade_node)
    rw_mod.rewrite_node         = _timed_node("rewrite",         rw_mod.rewrite_node)
    gap_mod.gap_report_node     = _timed_node("gap_report",      gap_mod.gap_report_node)
    llm_mod.llm_node            = _timed_node("llm",             llm_mod.llm_node)


# ── 主流程 ───────────────────────────────────────────────────────────
_case_summary: list[dict] = []


def run_case(case: dict, kb_dir: Path, case_index: int) -> None:
    global _node_timings
    _node_timings = []

    title = case["name"]
    query = case["input"]
    expect = case["expect_keywords"]

    print(f"\n{'═'*60}")
    print(f"問題 {case_index}：{title}")
    print(f"輸入：{query[:100]}...")
    print(f"{'═'*60}")

    t_total = time.perf_counter()

    _patch_rag_graph()

    from rag.rag_graph import build_rag_graph, ensure_local_index

    print(f"\n  [索引] 確認 KB index 狀態...")
    t_idx = time.perf_counter()
    ensure_local_index(kb_dir=kb_dir)
    idx_elapsed = time.perf_counter() - t_idx
    print(f"  [索引] 完成  耗時 {idx_elapsed:.2f}s")

    graph = build_rag_graph()
    result = graph.invoke({"original_input": query, "route": "kb"})

    rag_elapsed = sum(t["elapsed"] for t in _node_timings)
    total_elapsed = time.perf_counter() - t_total

    # ── 節點耗時明細 ──
    print(f"\n{'─'*55}")
    print(f"  節點耗時明細（問題 {case_index}）")
    print(f"{'─'*55}")
    for t in _node_timings:
        bar = "█" * min(int(t["elapsed"] * 2), 40)
        print(f"  {t['node']:20s}  {t['elapsed']:6.2f}s  {bar}")
    print(f"  {'─'*40}")
    print(f"  {'RAG 節點合計':20s}  {rag_elapsed:6.2f}s")
    print(f"  {'含索引+overhead':20s}  {total_elapsed:6.2f}s")

    # ── 最終輸出 ──
    rag_context = result.get("rag_context", "")
    print(f"\n  RAG 輸出（rag_context）：")
    if rag_context:
        print(f"  長度：{len(rag_context)} chars")
        print()
        for line in rag_context.splitlines()[:30]:
            print(f"  {line}")
        if len(rag_context.splitlines()) > 30:
            print(f"  ... (截略，共 {len(rag_context.splitlines())} 行)")
    else:
        print("  (rag_context 為空)")

    # ── 關鍵字驗證 ──
    found = [kw for kw in expect if kw.lower() in rag_context.lower()]
    missing = [kw for kw in expect if kw.lower() not in rag_context.lower()]
    print(f"\n  關鍵字驗證：找到 {found}" + (f"  / 未找到 {missing}" if missing else ""))

    # ── 記錄彙總 ──
    node_map: dict[str, float] = {}
    for t in _node_timings:
        node_map[t["node"]] = node_map.get(t["node"], 0) + t["elapsed"]
    crag_score = result.get("crag_score", None)
    _case_summary.append({
        "index": case_index,
        "title": title,
        "nodes": node_map,
        "rag_elapsed": rag_elapsed,
        "total_elapsed": total_elapsed,
        "crag_score": crag_score,
        "kb_hit": (crag_score or 0) >= 0.4,
        "kw_found": len(found),
        "kw_total": len(expect),
    })


def _print_summary(summary: list[dict], label: str) -> None:
    print(f"\n\n{'═'*72}")
    print(f"  {label}")
    print(f"{'═'*72}")
    print(f"  {'#':>2}  {'問題':30s}  {'input_planner':>13}  {'hybrid':>8}  {'rewrite':>8}  {'llm':>6}  {'RAG合計':>8}  {'score':>6}  KB命中")
    print(f"  {'─'*68}")
    for s in summary:
        n = s["nodes"]
        ip  = n.get("input_planner", 0)
        hr  = n.get("hybrid_retrieve", 0)
        rw  = n.get("rewrite", 0)
        llm = n.get("llm", 0)
        rag = s["rag_elapsed"]
        sc  = f"{s['crag_score']:.3f}" if s["crag_score"] is not None else "  N/A"
        hit = "Yes" if s["kb_hit"] else "No (gap)"
        print(f"  {s['index']:>2}  {s['title']:30s}  {ip:12.2f}s  {hr:7.2f}s  {rw:7.2f}s  {llm:5.2f}s  {rag:7.2f}s  {sc:>6}  {hit}")
    print(f"{'═'*72}")


def _set_llm_planner(enabled: bool) -> None:
    """直接改 input_planner 模組的模組層級變數（from-import 不受 rag_config 異動影響）。"""
    import rag.nodes.input_planner as _ip
    _ip.INPUT_PLANNER_USE_LLM = enabled


def main():
    print("BSP RAG CRAG — 直接計時測試")
    print(f"開始時間：{time.strftime('%Y-%m-%d %H:%M:%S')}")

    kb_dir = ROOT / "MIC-741_KnowledgeBase"
    if not kb_dir.exists():
        print(f"❌ KB 目錄不存在：{kb_dir}")
        sys.exit(1)

    # ── Mode A：Rule-based input_planner（預設，快）──
    global _case_summary
    _case_summary = []
    _set_llm_planner(False)
    print(f"\n{'▶'*3} Mode A：Rule-based input_planner（INPUT_PLANNER_USE_LLM=0）")
    for i, case in enumerate(TEST_CASES, 1):
        run_case(case, kb_dir, i)
    summary_a = list(_case_summary)
    _print_summary(summary_a, "Mode A — Rule-based input_planner（每題耗時）")

    # ── Mode B：LLM input_planner（原始，慢但語意更強）──
    _case_summary = []
    _set_llm_planner(True)
    print(f"\n{'▶'*3} Mode B：LLM input_planner（INPUT_PLANNER_USE_LLM=1）")
    for i, case in enumerate(TEST_CASES, 1):
        run_case(case, kb_dir, i)
    summary_b = list(_case_summary)
    _print_summary(summary_b, "Mode B — LLM input_planner（每題耗時）")

    # ── 對比差異 ──
    print(f"\n{'═'*72}")
    print(f"  Mode A vs Mode B 對比（input_planner 的影響）")
    print(f"{'═'*72}")
    print(f"  {'問題':30s}  {'A ip':>6}  {'B ip':>6}  {'差值':>8}  {'A RAG合計':>10}  {'B RAG合計':>10}  差值")
    print(f"  {'─'*68}")
    for a, b in zip(summary_a, summary_b):
        a_ip  = a["nodes"].get("input_planner", 0)
        b_ip  = b["nodes"].get("input_planner", 0)
        a_rag = a["rag_elapsed"]
        b_rag = b["rag_elapsed"]
        print(f"  {a['title']:30s}  {a_ip:5.2f}s  {b_ip:5.2f}s  +{b_ip-a_ip:6.2f}s  {a_rag:9.2f}s  {b_rag:9.2f}s  +{b_rag-a_rag:.2f}s")
    print(f"{'═'*72}")
    print(f"  完成時間：{time.strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
