"""Convert material/*.pdf → corpus/design-guide/*.md

Uses pdfplumber to extract text, applying simple heuristics to detect
section headings (short ALL-CAPS or numbered lines).

Usage:
    python etl/convert_pdf.py [--force]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MATERIAL_DIR = Path(__file__).parent.parent / "material"
CORPUS_DIR   = Path(__file__).parent.parent / "corpus" / "design-guide"

# Lines shorter than this and matching heading patterns → ## heading
_MAX_HEADING_LEN = 120


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > _MAX_HEADING_LEN:
        return False
    # Numbered section: "1.2.3 Some Title"
    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", s):
        return True
    # ALL CAPS short line (≥3 words or known keywords)
    if s.isupper() and len(s.split()) >= 2:
        return True
    return False


def _clean(text: str) -> str:
    """Remove excessive blank lines and trailing spaces."""
    lines = [l.rstrip() for l in text.splitlines()]
    out: list[str] = []
    blank = 0
    for line in lines:
        if not line:
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(line)
    return "\n".join(out).strip()


def convert_pdf(pdf_path: Path, output_dir: Path, force: bool = False) -> Path | None:
    try:
        import pdfplumber
    except ImportError:
        print("[ERROR] pdfplumber not installed. Run: uv add pdfplumber")
        sys.exit(1)

    out_path = output_dir / (pdf_path.stem + ".md")
    if out_path.exists() and not force:
        print(f"  [SKIP] {pdf_path.name} (already converted, use --force to redo)")
        return out_path

    output_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = [f"# {pdf_path.stem}\n"]

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            raw = page.extract_text()
            if not raw:
                continue

            page_lines: list[str] = []
            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped:
                    page_lines.append("")
                    continue
                if _is_heading(stripped):
                    page_lines.append(f"\n## {stripped}")
                else:
                    page_lines.append(stripped)

            page_text = _clean("\n".join(page_lines))
            if page_text:
                parts.append(f"\n<!-- page {i+1}/{total} -->\n{page_text}")

    content = "\n".join(parts)
    out_path.write_text(content, encoding="utf-8")
    size_kb = out_path.stat().st_size // 1024
    print(f"  [OK] {pdf_path.name} → {out_path.name} ({total} pages, {size_kb} KB)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert material PDFs to Markdown")
    parser.add_argument("--force", action="store_true", help="Re-convert even if output exists")
    args = parser.parse_args()

    pdfs = sorted(MATERIAL_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDF files found in {MATERIAL_DIR}")
        return

    print(f"Converting {len(pdfs)} PDF(s) → {CORPUS_DIR}/")
    for pdf in pdfs:
        convert_pdf(pdf, CORPUS_DIR, force=args.force)
    print("Done.")


if __name__ == "__main__":
    main()
