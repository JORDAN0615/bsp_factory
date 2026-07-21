"""RAG 功能驗證腳本

用法:
    python scripts/test_rag.py                          # 跑所有預設問題
    python scripts/test_rag.py "你的問題"               # 跑單一問題
    python scripts/test_rag.py --init                   # 只建 index，不查詢

第一次執行需要 --init 或直接查詢，會自動建立 Qdrant 磁碟 index（約 1-2 分鐘）。
之後每次啟動會直接從磁碟讀取，秒速完成。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 加入 bsp_factory 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))


PRESET_QUERIES = [
    # (描述, 問題, 預期結果)
    ("MGBE 網路 [應命中 KB]",
     "MIC-741 MGBE network interface fails to initialize, mdio bus error on JP7.1",
     "good"),

    ("CAN bus [應命中 KB]",
     "CAN bus not working after JP7.1 upgrade, mttcan driver fails to probe",
     "good"),

    ("PCIe NVMe [應命中 KB]",
     "second NVMe SSD not detected on PCIe C3 slot, MIC-741 JP7.2",
     "good"),

    ("Pinmux 衝突 [應命中 KB]",
     "I2C3 and CAN2 pin reserved conflict in pinmux, JP7.2 bringup",
     "good"),

    ("Bluetooth audio [應走 gap/LLM]",
     "Bluetooth audio codec fails with ALSA underrun errors on embedded Linux",
     "gap"),
]


def init_index() -> None:
    print("正在初始化 index（首次需要 1-2 分鐘，之後秒速）...")
    from rag.rag_graph import ensure_local_index
    ensure_local_index()
    print("Index 已就緒\n")


def run_query(question: str) -> dict:
    from rag.rag_graph import build_rag_graph
    rag = build_rag_graph()
    return rag.invoke({"original_input": question, "route": "kb"})


def print_result(label: str, question: str, result: dict, expected: str = "") -> None:
    context = result.get("rag_context", "")
    score = result.get("crag_score", 0.0)
    retries = result.get("retry_count", 0)

    # 判斷走的路徑
    if "LLM 推斷" in context or "知識庫無記錄" in context:
        path = "gap (LLM 推斷)"
    else:
        path = "good (知識庫命中)"

    status = ""
    if expected:
        ok = (expected == "gap") == ("gap" in path)
        status = "PASS" if ok else "FAIL"

    print("=" * 60)
    print(f"[{status}] {label}" if status else f"[ ] {label}")
    print(f"問題: {question}")
    print(f"路徑: {path}  |  score={score:.3f}  |  retries={retries}")
    print()
    print(context.strip())
    print()


def main() -> None:
    args = sys.argv[1:]

    init_index()

    if "--init" in args:
        print("Index 建立完成，可以開始查詢。")
        return

    if args and not args[0].startswith("--"):
        # 單一問題
        question = args[0]
        print(f"查詢: {question}\n")
        result = run_query(question)
        print_result("自訂查詢", question, result)
    else:
        # 跑所有預設問題
        print(f"執行 {len(PRESET_QUERIES)} 個預設測試問題...\n")
        passed = 0
        for label, question, expected in PRESET_QUERIES:
            result = run_query(question)
            print_result(label, question, result, expected)
            score = result.get("crag_score", 0.0)
            gap = "LLM 推斷" in result.get("rag_context", "")
            if (expected == "gap") == gap:
                passed += 1

        print("=" * 60)
        print(f"結果: {passed}/{len(PRESET_QUERIES)} PASS")


if __name__ == "__main__":
    main()
