from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from agent.tools.doc_ingest.manifest import ManifestSource
from agent.tools.doc_ingest.records import ChunkRecord, IngestedRecords
from agent.tools.mic741_knowledge import KnowledgeDBError, _extract_symbols


_PROSE_BUDGET_CHARS = 2000
_PROSE_OVERLAP = 0.15
_MIN_PROSE_CHARS = 50
_MIN_TABLE_CHARS = 50
_HEADING_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\s+\S")
_FIGURE_CAPTION = re.compile(r"^(?:figure|fig\.)\s*\d+", re.IGNORECASE)
_CAPTION_LINE = re.compile(r"^(?:figure|fig\.|table)\s*\d", re.IGNORECASE)
_DOCUMENT_IDENTIFIER = re.compile(r"[A-Z]{2,3}-\d{4,5}-\d{3}")
_DOT_LEADER = re.compile(r"\.{5,}")


def ingest_pdf(source: ManifestSource) -> IngestedRecords:
    try:
        import fitz
    except ImportError as exc:
        raise KnowledgeDBError("PyMuPDF is required for PDF document ingestion") from exc

    chunks: list[ChunkRecord] = []
    with fitz.open(source.path) as document:
        page_lines = [
            [_normalize_line(line) for line in page.get_text("text", sort=True).splitlines()]
            for page in document
        ]
        boilerplate = detect_boilerplate(page_lines)
        section_parts: list[str] = []
        current_section: list[str] = []

        for page_index, page in enumerate(document):
            page_number = page_index + 1
            table_finder = page.find_tables()
            tables = list(table_finder.tables)
            table_boxes = [fitz.Rect(table.bbox) for table in tables]
            for table in tables:
                content = _render_table(table.extract())
                if len(content.strip()) >= _MIN_TABLE_CHARS:
                    chunks.append(
                        ChunkRecord(
                            chunk_type="table",
                            page=page_number,
                            section_path=_section_text(current_section),
                            content=content,
                            symbols=_extract_symbols(content),
                        )
                    )

            blocks = page.get_text("blocks", sort=True)
            prose_blocks: list[tuple[Any, str]] = []
            for block in blocks:
                box = fitz.Rect(block[:4])
                if any(box.intersects(table_box) for table_box in table_boxes):
                    continue
                text = _strip_boilerplate(str(block[4]), boilerplate)
                if text:
                    prose_blocks.append((box, text))

            for _, block_text in prose_blocks:
                for paragraph in _paragraphs(block_text):
                    if _is_heading(paragraph):
                        _emit_prose_chunks(
                            chunks,
                            section_parts,
                            current_section,
                            page_number,
                        )
                        section_parts = []
                        current_section = _updated_section(current_section, paragraph)
                    else:
                        section_parts.append(paragraph)
            _emit_prose_chunks(chunks, section_parts, current_section, page_number)
            section_parts = []

            _emit_figure_ref(
                chunks,
                page,
                prose_blocks,
                current_section,
                page_number,
            )
        return IngestedRecords(page_count=len(document), chunks=chunks)


def detect_boilerplate(page_lines: list[list[str]]) -> set[str]:
    if not page_lines:
        return set()
    counts: Counter[str] = Counter()
    for lines in page_lines:
        counts.update(
            {
                key
                for line in lines
                if (key := _boilerplate_key(line)) and not _CAPTION_LINE.match(key)
            }
        )
    threshold = len(page_lines) / 2
    return {line for line, count in counts.items() if count > threshold}


def chunk_prose(
    paragraphs: list[str],
    *,
    budget_chars: int = _PROSE_BUDGET_CHARS,
    overlap: float = _PROSE_OVERLAP,
) -> list[str]:
    cleaned = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
    if not cleaned:
        return []
    overlap_chars = max(0, int(budget_chars * overlap))
    chunks: list[str] = []
    current: list[str] = []

    for paragraph in cleaned:
        if len(paragraph) > budget_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
            step = max(1, budget_chars - overlap_chars)
            chunks.extend(
                paragraph[start : start + budget_chars]
                for start in range(0, len(paragraph), step)
                if paragraph[start : start + budget_chars]
            )
            continue

        candidate = "\n\n".join([*current, paragraph])
        if current and len(candidate) > budget_chars:
            chunks.append("\n\n".join(current))
            current = _overlap_paragraphs(current, overlap_chars)
            while current and len("\n\n".join([*current, paragraph])) > budget_chars:
                current.pop(0)
        current.append(paragraph)

    if current:
        final = "\n\n".join(current)
        if not chunks or final != chunks[-1]:
            chunks.append(final)
    return chunks


def _overlap_paragraphs(paragraphs: list[str], target_chars: int) -> list[str]:
    if target_chars <= 0:
        return []
    carried: list[str] = []
    size = 0
    for paragraph in reversed(paragraphs):
        carried.insert(0, paragraph)
        size += len(paragraph) + (2 if len(carried) > 1 else 0)
        if size >= target_chars:
            break
    return carried


def _emit_prose_chunks(
    output: list[ChunkRecord],
    paragraphs: list[str],
    section: list[str],
    page: int,
) -> None:
    useful_paragraphs = [paragraph for paragraph in paragraphs if not _DOT_LEADER.search(paragraph)]
    for content in chunk_prose(useful_paragraphs):
        if len(content.strip()) < _MIN_PROSE_CHARS:
            continue
        output.append(
            ChunkRecord(
                chunk_type="prose",
                section_path=_section_text(section),
                page=page,
                content=content,
                symbols=_extract_symbols(content),
            )
        )


def _strip_boilerplate(text: str, boilerplate: set[str]) -> str:
    return "\n".join(
        line
        for line in (_normalize_line(line) for line in text.splitlines())
        if line and _boilerplate_key(line) not in boilerplate
    ).strip()


def _paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text)
    paragraphs: list[str] = []
    for block in blocks:
        lines = [_normalize_line(line) for line in block.splitlines() if _normalize_line(line)]
        if not lines:
            continue
        if len(lines) == 1:
            paragraphs.append(lines[0])
        else:
            paragraphs.append(" ".join(lines))
    return paragraphs


def _is_heading(text: str) -> bool:
    line = _normalize_line(text)
    if not line or len(line) > 120 or len(line.split()) > 14:
        return False
    if _DOCUMENT_IDENTIFIER.search(line):
        return False
    if _HEADING_NUMBER.match(line):
        return True
    if line.endswith((".", ";", ",")):
        return False
    words = [word for word in re.findall(r"[A-Za-z][A-Za-z0-9/-]*", line) if word]
    if not words:
        return False
    title_words = sum(word[0].isupper() for word in words)
    return line.isupper() or title_words / len(words) >= 0.7


def _updated_section(current: list[str], heading: str) -> list[str]:
    numbered = _HEADING_NUMBER.match(heading)
    if not numbered:
        return [heading]
    depth = numbered.group(1).count(".") + 1
    return [*current[: depth - 1], heading]


def _section_text(section: list[str]) -> str | None:
    return " > ".join(section) if section else None


def _render_table(rows: list[list[Any]] | None) -> str:
    rendered: list[str] = []
    for row in rows or []:
        cells = [
            normalized
            for cell in row
            if cell is not None and (normalized := _normalize_line(str(cell)))
        ]
        if cells:
            rendered.append(" | ".join(cells))
    return "\n".join(rendered)


def _nearest_caption(page: Any, blocks: list[tuple[Any, str]]) -> str | None:
    candidates = [(box, text) for box, text in blocks if _FIGURE_CAPTION.match(text)]
    if not candidates:
        return None
    try:
        image_boxes = [page.rect.__class__(info["bbox"]) for info in page.get_image_info()]
    except (KeyError, TypeError, ValueError):
        image_boxes = []
    if not image_boxes:
        return candidates[0][1]

    def distance(item: tuple[Any, str]) -> float:
        box = item[0]
        return min(
            math.hypot(box.x0 - image.x0, box.y0 - image.y0)
            for image in image_boxes
        )

    return min(candidates, key=distance)[1]


def _emit_figure_ref(
    output: list[ChunkRecord],
    page: Any,
    prose_blocks: list[tuple[Any, str]],
    section: list[str],
    page_number: int,
) -> None:
    if not page.get_images(full=True):
        return
    caption = _nearest_caption(page, prose_blocks)
    if not caption:
        return
    content = f"Figure reference on page {page_number}. Caption: {caption}"
    output.append(
        ChunkRecord(
            chunk_type="figure_ref",
            page=page_number,
            section_path=_section_text(section),
            content=content,
            symbols=_extract_symbols(content),
        )
    )


def _boilerplate_key(line: str) -> str:
    text = _normalize_line(line)
    if _CAPTION_LINE.match(text):
        return text
    if re.fullmatch(r"\d{1,4}", text):
        return "<page-number>"
    text = re.sub(r"\s*\|\s*\d{1,4}\s*$", "", text)
    text = re.sub(r"^\s*\d{1,4}\s*\|\s*", "", text)
    return text


def _normalize_line(value: str) -> str:
    return " ".join(value.split())
