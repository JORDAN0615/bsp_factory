"""DB Ingestion pipeline — parses MIC-741_KnowledgeBase/01_Issues/*.md.

Pushes structured data into:
  - PostgreSQL  (bsp_cases table)
  - Neo4j       (Component/Driver/Error/Fix graph)

All operations are idempotent (upsert / MERGE).
Run manually:  python -m db.ingestion
"""

from __future__ import annotations

import os
import re
from pathlib import Path

KB_DIR = Path(os.getenv("KB_DIR", "MIC-741_KnowledgeBase"))
ISSUES_DIR = KB_DIR / "01_Issues"

# ── Component tag mapping (from title brackets and keywords) ──────────────────

_TAG_COMPONENT: dict[str, str] = {
    "GPU":    "GPU",
    "LAN":    "MGBE",
    "CAN":    "CAN bus",
    "PCIE":   "PCIe",
    "PCIe":   "PCIe",
    "USB":    "USB",
    "CAM":    "camera",
    "SPI":    "SPI bus",
    "I2C":    "I2C bus",
    "UART":   "UART",
    "PINMUX": "pinctrl",
    "GPIO":   "GPIO",
    "BOOT":   "bootloader",
    "NVME":   "storage",
    "SOM":    "SoM",
}

_KEYWORD_COMPONENT: list[tuple[list[str], str]] = [
    (["mgbe", "aquantia", "10g", "mdio", "ether", "lan"],  "MGBE"),
    (["nvpmodel", "gpu", "power plan"],                     "GPU"),
    (["canbus", "can bus", "mcp2518", "mttcan"],            "CAN bus"),
    (["pcie", "nvme", "c3"],                                "PCIe"),
    (["camera", "sipl", "mipi", "csi"],                     "camera"),
    (["spi"],                                               "SPI bus"),
    (["pinmux", "pinctrl", "pin"],                          "pinctrl"),
    (["bootloader", "mb1 bct", "flash config"],             "bootloader"),
    (["som", "t5000", "t4000", "module"],                   "SoM"),
    (["storage", "nvme", "emmc"],                           "storage"),
    (["usb"],                                               "USB"),
]


def _detect_component(title: str, body: str, source_ref: str = "") -> str:
    """Detect component from title [TAG], filename, or keyword matching on body.

    Priority: title bracket > filename > body keywords.
    Filename is checked before body to avoid misclassification when a component
    is mentioned in passing (e.g. MGBE mentioned in a PCIe fix description).
    """
    # 1. Title brackets (most reliable)
    for tag, comp in _TAG_COMPONENT.items():
        if f"[{tag}]" in title or f"[{tag.upper()}]" in title.upper():
            return comp
    # 2. Filename keywords (e.g. RE-15_enable-pcie-c3-2nd-nvme → PCIe)
    filename_lower = source_ref.lower()
    for keywords, comp in _KEYWORD_COMPONENT:
        if any(k in filename_lower for k in keywords):
            return comp
    # 3. Body keyword fallback
    text = (title + " " + body[:300]).lower()
    for keywords, comp in _KEYWORD_COMPONENT:
        if any(k in text for k in keywords):
            return comp
    return "kernel"


# ── Markdown parser ───────────────────────────────────────────────────────────

def _parse_table(text: str) -> dict[str, str]:
    """Extract key→value from markdown table rows."""
    meta: dict[str, str] = {}
    for m in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", text, re.MULTILINE):
        key = re.sub(r"[\*`_]", "", m.group(1)).strip().lower()
        val = re.sub(r"[\*`_]", "", m.group(2)).strip()
        if key and val and key != "欄位" and key != "---":
            meta[key] = val
    return meta


def _extract_section(text: str, *names: str) -> str:
    """Extract content of a ## section (first match among names)."""
    for name in names:
        pattern = rf"^##\s+{re.escape(name)}.*?$\n([\s\S]*?)(?=\n##\s|\Z)"
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""


def _bsp_version_from_text(text: str) -> str:
    """Try to extract BSP version string from arbitrary text."""
    m = re.search(r"[Vv](\d+\.\d+\.\d+)", text)
    return m.group(0).upper() if m else ""


def _parse_issue_md(path: Path) -> dict | None:
    """Parse one issue md file into a structured record."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Title
    title_m = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else path.stem

    meta = _parse_table(text)

    # issue_id: Bug ID (ISSUE-Gxxxxx) or RE-XX from filename
    issue_id = (
        meta.get("bug id")
        or meta.get("反推來源 commit", "")[:8]
        or path.stem
    )
    source_ref = path.stem  # e.g. "ISSUE-G42005_GPU-nvpmodel"

    # model
    model_raw = meta.get("pcb / model", meta.get("pcb/model", "MIC-741"))
    model = re.match(r"MIC-\d+", model_raw)
    model = model.group(0) if model else "MIC-741"

    # bsp_version
    solution_area = meta.get("final solution area", "")
    bsp_version = _bsp_version_from_text(solution_area) or _bsp_version_from_text(text) or ""

    # status
    status_raw = meta.get("狀態", meta.get("類型", ""))
    status = "RESOLVED" if "close" in status_raw.lower() or "fix" in status_raw.lower() else "OPEN"

    # date
    date_raw = meta.get("resolved", meta.get("日期", meta.get("close", "")))
    date_clean = re.match(r"\d{4}-\d{2}-\d{2}", date_raw or "")
    date = date_clean.group(0) if date_clean else None

    # error_msg: from 問題描述 or 問題 / 目標 section
    error_msg = _extract_section(
        text,
        "問題描述 (Symptom)", "問題描述", "問題 / 目標（反推）", "問題 / 目標", "問題"
    )

    # fix_summary: from 解法 section
    fix_raw = _extract_section(
        text,
        "解法 (Resolution — alex.hsu)", "解法 (Resolution)", "解法（實際 commit 做法）", "解法"
    )
    # Use first 2 non-empty lines as summary
    fix_lines = [l.strip("- >").strip() for l in fix_raw.splitlines() if l.strip()]
    fix_summary = " ".join(fix_lines[:3])

    component = _detect_component(title, error_msg + " " + fix_raw, source_ref)

    # driver: main files field or component name
    driver_raw = meta.get("主要檔案", "")
    driver = driver_raw.split("、")[0].strip() if driver_raw else component

    return {
        "source_ref":   source_ref,
        "issue_id":     issue_id,
        "title":        title,
        "model":        model,
        "bsp_version":  bsp_version,
        "component":    component,
        "driver":       driver,
        "test_item":    title[:100],
        "category":     component,
        "status":       status,
        "error_code":   None,
        "error_msg":    error_msg[:2000] if error_msg else None,
        "fix_summary":  fix_summary[:500] if fix_summary else None,
        "fix_steps":    [l.strip("- ").strip() for l in fix_raw.splitlines() if l.strip()][:10],
        "verified":     status == "RESOLVED",
        "source":       "issue_md",
        "date":         date,
    }


# ── Ingestion functions ───────────────────────────────────────────────────────

def _ingest_issue_mds(pg_available: bool, neo4j_available: bool) -> int:
    if not ISSUES_DIR.exists():
        print(f"[INGEST] Issues dir not found: {ISSUES_DIR}")
        return 0

    count = 0
    for md_path in sorted(ISSUES_DIR.glob("*.md")):
        if md_path.name in ("RE-INDEX.md",):
            continue

        rec = _parse_issue_md(md_path)
        if rec is None:
            continue

        if pg_available:
            from db.postgres import insert_case
            insert_case({
                "model":        rec["model"],
                "bsp_version":  rec["bsp_version"],
                "component":    rec["component"],
                "test_item":    rec["test_item"],
                "category":     rec["category"],
                "status":       rec["status"],
                "error_code":   rec["error_code"],
                "error_msg":    rec["error_msg"],
                "fix_summary":  rec["fix_summary"],
                "verified":     rec["verified"],
                "source":       rec["source"],
                "date":         rec["date"],
                "source_ref":   rec["source_ref"],
            })

        if neo4j_available and rec.get("error_msg") and rec.get("fix_summary"):
            from db.neo4j_client import ingest_case
            ingest_case(
                model=rec["model"],
                bsp_version=rec["bsp_version"],
                driver_name=rec["driver"],
                component_name=rec["component"],
                error_msg=rec["error_msg"][:500],
                fix_description=rec["fix_summary"],
                fix_steps=rec["fix_steps"],
                verified=rec["verified"],
            )

        count += 1
        print(f"  [OK] {md_path.name} → component={rec['component']}, status={rec['status']}")

    return count


# ── Public entry point ────────────────────────────────────────────────────────

def run_ingestion(pg_available: bool, neo4j_available: bool) -> dict[str, int]:
    """Ingest all KB issue md files. Returns row counts per source."""
    if pg_available:
        from db.postgres import init_schema
        init_schema()

    if neo4j_available:
        from db.neo4j_client import init_schema as neo4j_init
        neo4j_init()

    counts: dict[str, int] = {}
    counts["issue_mds"] = _ingest_issue_mds(pg_available, neo4j_available)
    return counts


if __name__ == "__main__":
    from db.postgres import is_available as pg_ok
    from db.neo4j_client import is_available as neo4j_ok
    _pg = pg_ok()
    _neo = neo4j_ok()
    print(f"PostgreSQL: {'OK' if _pg else 'skip'}  Neo4j: {'OK' if _neo else 'skip'}")
    result = run_ingestion(_pg, _neo)
    print(f"\nIngestion complete: {result}")
