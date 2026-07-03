"""RAG evaluation: TP / TN / FP / FN coverage test.

Expected results:
  TP: KB has the answer, should retrieve correctly with citations
  TN: KB has no exact match, should give inferred answer (not refuse)
  FP: Query that sounds related but KB has no direct case — should NOT fabricate citations
  FN: KB has the case but query is phrased differently — should still find it
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

from rag_integration import query_rag

CASES = [
    # ── True Positive (KB 裡有完整紀錄) ───────────────────────────────────────
    ("TP-1", "EA graphic driver 造成 GPU 功能異常，需要從 BSP 移除",
     "expect: RE-03, citations from KB, confidence=verified"),

    ("TP-2", "MGBE1 RST GPIO pin 與其他功能衝突導致網路失效",
     "expect: RE-11, MGBE component, citations from KB"),

    ("TP-3", "第二個 NVMe M.2 slot 在 Jetson Thor PCIe C3 上無法被偵測",
     "expect: RE-15 or RE-09, PCIe component, citations from KB"),

    # ── True Negative (KB 沒有直接記錄，但 LLM 應嘗試推斷修復) ──────────────
    ("TN-1", "WiFi 802.11ac 驅動在 Jetson Thor 上無法載入，dmesg 顯示 firmware load failed",
     "expect: inferred answer, no citations, confidence=inferred, ⚠️ label"),

    ("TN-2", "USB 3.0 裝置在進入 suspend 後隨機斷線",
     "expect: inferred answer about USB power management, ⚠️ label"),

    # ── False Positive 測試 (不應該亂引用 KB) ─────────────────────────────────
    ("FP-test", "HDMI 輸出在開機過程中閃爍，連接 4K 螢幕",
     "expect: inferred answer OR empty citations, must NOT cite unrelated KB entries"),

    # ── False Negative 測試 (不同說法但 KB 有相關案例) ────────────────────────
    ("FN-1", "network interface fails to link up on first boot after flashing",
     "expect: should find MGBE issue (RE-01 or ISSUE-G42006) even though query is English"),

    ("FN-2", "MCP2518FD interrupt not working after JP7.2 update",
     "expect: should find RE-19 (CAN interrupt pinmux fix), citations from KB"),
]

PASS = 0
WARN = 0
FAIL = 0

for tag, query, expectation in CASES:
    print("\n" + "=" * 70)
    print(f"[{tag}] {query}")
    print(f"Expectation: {expectation}")
    print("=" * 70)

    result = query_rag(query)

    score   = result["crag_score"]
    source  = result["source"]
    cites   = result["citations"]
    answer  = result["answer"]

    print(f"score={score:.3f}  source={source}  citations={cites}")
    print("--- answer ---")
    print(answer[:600])

    # Simple heuristic checks
    inferred = "⚠️" in answer or "推斷" in answer
    has_cites = len(cites) > 0

    if tag.startswith("TP"):
        if has_cites and score >= 0.4:
            print("[PASS] KB citations found, score OK")
            PASS += 1
        else:
            print("[FAIL] expected KB citations")
            FAIL += 1

    elif tag.startswith("TN"):
        if len(answer) > 100 and ("步驟" in answer or "建議" in answer or "step" in answer.lower()):
            print("[PASS] gave actionable inferred answer")
            PASS += 1
        else:
            print("[WARN] answer might be too vague")
            WARN += 1

    elif tag == "FP-test":
        if has_cites:
            print("[WARN] citations present -- check if they are actually relevant")
            WARN += 1
        else:
            print("[PASS] no spurious citations")
            PASS += 1

    elif tag.startswith("FN"):
        if has_cites and score >= 0.5:
            print("[PASS] cross-phrasing retrieval succeeded")
            PASS += 1
        else:
            print("[WARN] may have missed KB entry (FN)")
            WARN += 1

print("\n" + "=" * 70)
print(f"Result: PASS={PASS}  WARN={WARN}  FAIL={FAIL}  Total={len(CASES)}")
print("=" * 70)
