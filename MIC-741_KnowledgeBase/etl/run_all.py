"""Run all ETL conversions: PDF + Excel → corpus/

Usage:
    python etl/run_all.py [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure we can import sibling scripts
sys.path.insert(0, str(Path(__file__).parent))

from convert_pdf     import convert_pdf,  MATERIAL_DIR as PDF_DIR,   CORPUS_DIR as PDF_OUT
from convert_pinmux  import convert_xlsm, MATERIAL_DIR as XLSM_DIR,  CORPUS_DIR as XLSM_OUT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all KB ETL conversions")
    parser.add_argument("--force", action="store_true", help="Re-convert even if output exists")
    args = parser.parse_args()

    print("=" * 60)
    print("Step 1: PDF → corpus/design-guide/")
    print("=" * 60)
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        convert_pdf(pdf, PDF_OUT, force=args.force)

    print()
    print("=" * 60)
    print("Step 2: Excel → corpus/pinmux/")
    print("=" * 60)
    for xls in sorted(XLSM_DIR.glob("*.xls*")):
        convert_xlsm(xls, XLSM_OUT, force=args.force)

    print()
    print("All done. Markdown files are in:")
    print(f"  {PDF_OUT}")
    print(f"  {XLSM_OUT}")
    print()
    print("Next: rebuild the Qdrant index to pick up the new corpus/")
    print("  uv run python -c \"from rag.indexer import build_index; build_index(force=True)\"")


if __name__ == "__main__":
    main()
