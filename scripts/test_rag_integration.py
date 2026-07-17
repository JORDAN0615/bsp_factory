"""Integration test for retrieve_rag_crag_node.

Simulates the RepairGraphState that flows through the colleague's graph
and verifies our RAG node produces usable knowledge_context.

Usage:
    python scripts/test_rag_integration.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Set BEFORE any HuggingFace/sentence-transformers imports to skip hub network checks.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Ensure project root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Test cases (same format as colleague's graph input) ───────────────────────

TEST_CASES = [
    {
        "issue": (
            "MGBE failed up connection automatically when 1st boot to desktop. "
            "The ethernet link does not come up after first boot, manual ifconfig restart required."
        ),
        "error_signatures": ["MGBE", "ethernet link down", "ifconfig"],
        "existing_fts_context": "",  # FTS disabled → empty
    },
    {
        "issue": (
            "Camera probe failed with i2c -121 error. "
            "dmesg shows: imx390 0-001b: probe failed. i2c transfer timed out."
        ),
        "error_signatures": ["i2c -121", "imx390 probe failed", "camera probe"],
        "existing_fts_context": "## MIC-741 Knowledge Matches\n\n(disabled)\n",
    },
    {
        "issue": (
            "USB device not detected after hot-plug. "
            "lsusb shows nothing, dmesg shows usb 1-1: USB disconnect."
        ),
        "error_signatures": ["USB disconnect", "usb hub", "lsusb empty"],
        "existing_fts_context": "",
    },
]


def run_test(case: dict, settings, verbose: bool = True) -> bool:
    from agent.graph import retrieve_rag_crag_node
    from agent.state import BSPAgentState

    issue = case["issue"]
    print(f"\n{'='*60}")
    print(f"Issue: {issue[:80]}...")
    print(f"Error signatures: {case['error_signatures']}")

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "test-run-001"
        run_dir.mkdir()

        state = BSPAgentState(
            run_id="test-run-001",
            run_dir=str(run_dir),
            repo_path=str(Path(".")),
            issue=issue,
            stage="retrieve_mic741_knowledge",
            input_logs=[],
        )
        # Simulate what classify_error_node would have set
        state.current_attempt.error_signatures = case["error_signatures"]
        state.current_attempt.bug_type = "unknown"

        graph_state = {
            "state": state,
            "settings": settings,
            "logs_text": [],
            "skill_text": "",
            "knowledge_context": case["existing_fts_context"],
        }

        print("\nCalling retrieve_rag_crag_node ...")
        result = retrieve_rag_crag_node(graph_state)

        knowledge_context = result.get("knowledge_context", case["existing_fts_context"])
        rag_debug = (run_dir / "test-run-001" / "attempts" / "001" / "debug" / "rag_crag_context.md")

        if not knowledge_context or knowledge_context == case["existing_fts_context"]:
            print("FAIL — knowledge_context not populated by RAG")
            return False

        lines = knowledge_context.strip().splitlines()
        print(f"OK — knowledge_context: {len(lines)} lines")
        if verbose:
            preview = "\n".join(lines[:15])
            print(f"\n--- Context preview (first 15 lines) ---\n{preview}")
            if len(lines) > 15:
                print(f"... ({len(lines) - 15} more lines)")

        return True


def main() -> None:
    from pathlib import Path
    from agent.config import Settings

    print("BSP Agent — RAG CRAG Integration Test")
    print("=" * 60)

    # Override settings: enable RAG CRAG, point to local KB
    os.environ["RAG_CRAG_ENABLED"] = "true"
    # Use absolute path so cache checksum is stable across invocations.
    os.environ["MIC741_KNOWLEDGE_SOURCE_DIR"] = str((ROOT / "MIC-741_KnowledgeBase").resolve())

    settings = Settings()
    print(f"rag_crag_enabled       : {settings.rag_crag_enabled}")
    print(f"mic741_knowledge_source: {settings.mic741_knowledge_source_dir}")
    print(f"KB exists              : {settings.mic741_knowledge_source_dir.exists()}")

    if not settings.mic741_knowledge_source_dir.exists():
        print("\nERROR: KB directory not found. Run with the correct MIC741_KNOWLEDGE_SOURCE_DIR.")
        sys.exit(1)

    passed = 0
    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n[Test {i}/{len(TEST_CASES)}]")
        try:
            ok = run_test(case, settings, verbose=(i == 1))
            passed += ok
        except Exception as exc:
            print(f"ERROR: {exc}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Result: {passed}/{len(TEST_CASES)} passed")
    sys.exit(0 if passed == len(TEST_CASES) else 1)


if __name__ == "__main__":
    main()
