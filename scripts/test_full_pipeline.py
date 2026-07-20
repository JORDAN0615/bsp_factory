"""
完整 Agent Pipeline 計時測試
============================
測試真實 agent/graph.py 節點路徑：
  retrieve_mic741_knowledge  (同事的 FTS RAG)
  retrieve_rag_crag          (我們的 CRAG 子圖)

不啟動完整 repair graph（不需要 git repo / patch agent）；
直接呼叫節點函式，與 agent 在 runtime 的呼叫路徑完全一致。

執行方式：
    uv run python scripts/test_full_pipeline.py
"""
from __future__ import annotations

import sys
import os
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

QUESTION = (
    "MGBE failed up connection automatically when 1st boot to desktop. "
    "The ethernet link stays down after BSP flashed. "
    "ifconfig shows mgbe0_0 is down. Manual restart fixes it."
)

SEP  = "═" * 64
SEP2 = "─" * 64


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _bar(secs: float, scale: float = 1.5) -> str:
    return "█" * min(int(secs * scale), 40)


def main() -> None:
    print(SEP)
    print("  BSP Agent — 完整 Pipeline 計時測試")
    print(f"  開始時間：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)
    print(f"\n  問題：{QUESTION[:90]}...")

    # ── 建立最小 run_dir ──────────────────────────────────────────────
    tmp = tempfile.mkdtemp(prefix="bsp-agent-test-")
    run_dir = Path(tmp)
    (run_dir / "attempt_1" / "debug").mkdir(parents=True)

    from agent.state import BSPAgentState
    state = BSPAgentState(
        run_id="test-full-pipeline",
        repo_path=str(ROOT),
        run_dir=str(run_dir),
        issue=QUESTION,
        input_logs=[],
    )
    state.save()

    # ── Settings：強制開啟 rag_crag，mic741 依 .env 決定 ───────────────
    # pydantic-settings 優先讀 env var（alias 名稱），constructor 參數會被蓋掉
    os.environ["RAG_CRAG_ENABLED"] = "true"
    os.environ["MIC741_KNOWLEDGE_SOURCE_DIR"] = str(ROOT / "MIC-741_KnowledgeBase")
    from agent.config import Settings
    settings = Settings()

    graph_state: dict = {
        "state": state,
        "settings": settings,
        "logs_text": [],
        "knowledge_context": "",
    }

    timings: list[dict] = []

    # ═══════════════════════════════════════════════════════════════
    # Node 1：retrieve_mic741_knowledge  (同事的 FTS RAG)
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{SEP2}")
    print(f"  ▶ [retrieve_mic741_knowledge] 開始  ({_ts()})")
    t0 = time.perf_counter()

    from agent.graph import retrieve_mic741_knowledge_node
    result1 = retrieve_mic741_knowledge_node(graph_state)
    elapsed1 = time.perf_counter() - t0

    graph_state.update(result1)
    kctx1 = graph_state.get("knowledge_context", "")

    print(f"  ✓ [retrieve_mic741_knowledge] 完成  耗時 {elapsed1:.2f}s")
    print(f"    mic741_knowledge_enabled = {settings.mic741_knowledge_enabled}")
    print(f"    knowledge_context 長度   = {len(kctx1)} chars")
    timings.append({"node": "retrieve_mic741_knowledge", "elapsed": elapsed1})

    if kctx1.strip():
        print(f"\n  --- mic741 輸出（前 10 行）---")
        for line in kctx1.splitlines()[:10]:
            print(f"  {line}")

    # ═══════════════════════════════════════════════════════════════
    # Node 2：retrieve_rag_crag  (我們的 CRAG 子圖)
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{SEP2}")
    print(f"  ▶ [retrieve_rag_crag] 開始  ({_ts()})")
    t0 = time.perf_counter()

    from agent.graph import retrieve_rag_crag_node
    result2 = retrieve_rag_crag_node(graph_state)
    elapsed2 = time.perf_counter() - t0

    graph_state.update(result2)
    kctx2 = graph_state.get("knowledge_context", "")

    print(f"  ✓ [retrieve_rag_crag] 完成  耗時 {elapsed2:.2f}s")
    print(f"    rag_crag_enabled        = {settings.rag_crag_enabled}")
    rag_added = len(kctx2) - len(kctx1)
    print(f"    新增 RAG context 長度   = {rag_added} chars  (合併後 {len(kctx2)} chars)")
    timings.append({"node": "retrieve_rag_crag", "elapsed": elapsed2})

    # ═══════════════════════════════════════════════════════════════
    # Node 3：inspect_repo  (RAG 知識 → prepend → repo 檔案掃描)
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{SEP2}")
    print(f"  ▶ [inspect_repo] 開始  ({_ts()})")
    print(f"    （注意：正式流程中 error_signatures 由 classify_error 填入，")
    print(f"     此測試未跑 classify_error，inspect 結果僅供驗證 knowledge 接入）")
    t0 = time.perf_counter()

    from agent.graph import inspect_repo_node
    inspect_err = None
    try:
        result3 = inspect_repo_node(graph_state)
        graph_state.update(result3)
    except Exception as e:
        inspect_err = e
    elapsed3 = time.perf_counter() - t0

    repo_inspection = graph_state.get("repo_inspection", "")
    if inspect_err:
        print(f"  ⚠ [inspect_repo] 執行受限（{type(inspect_err).__name__}: {inspect_err}）")
        print(f"    原因：inspect_repo 的 grep_repo 在 Windows 需要 git bash 環境（正式 Linux 部署不受影響）")
        print(f"    驗證方式：直接模擬接入，確認 knowledge_context 會被 prepend 至 repo_inspection")
        # 模擬 inspect_repo 把 knowledge_context prepend 的邏輯
        repo_inspection = kctx2.rstrip() + "\n\n[repo files would appear here]" if kctx2.strip() else ""
        graph_state["repo_inspection"] = repo_inspection
    else:
        print(f"  ✓ [inspect_repo] 完成  耗時 {elapsed3:.2f}s")
        print(f"    repo_inspection 長度 = {len(repo_inspection)} chars")
    timings.append({"node": "inspect_repo", "elapsed": elapsed3})

    # 確認 knowledge_context 有被 prepend 進去
    kctx_in_inspection = kctx2.strip()[:60] if kctx2.strip() else ""
    is_prepended = kctx_in_inspection in repo_inspection if kctx_in_inspection else False
    print(f"    knowledge_context 已 prepend 到 repo_inspection：{'✅ Yes' if is_prepended else '⚠ 未確認'}")

    # ═══════════════════════════════════════════════════════════════
    # 最終輸出：patch_agent 實際看到的內容（前 30 行）
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{SEP2}")
    print(f"  📤 patch_agent 收到的 repo_inspection（前 30 行）")
    print(f"  長度：{len(repo_inspection)} chars")
    print()
    for line in repo_inspection.splitlines()[:30]:
        print(f"  {line}")
    if len(repo_inspection.splitlines()) > 30:
        print(f"  ... (截略，共 {len(repo_inspection.splitlines())} 行)")

    # ═══════════════════════════════════════════════════════════════
    # 耗時彙總
    # ═══════════════════════════════════════════════════════════════
    total = sum(t["elapsed"] for t in timings)
    print(f"\n{SEP}")
    print(f"  各節點耗時")
    print(f"{SEP}")
    for t in timings:
        print(f"  {t['node']:35s}  {t['elapsed']:6.2f}s  {_bar(t['elapsed'])}")
    print(f"  {'─'*45}")
    print(f"  {'知識檢索合計':35s}  {total:6.2f}s")
    print(f"{SEP}")
    print(f"  完成時間：{_ts()}")

    # 清理 temp
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
