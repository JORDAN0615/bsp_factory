from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.tools.mic741_knowledge import KnowledgeDBError, _read_text_artifact


_DOC_TYPES = {"design_guide", "datasheet", "pinmux_template"}
_REQUIRED_FIELDS = ("path", "doc_key", "title", "type", "platform", "version")


@dataclass(frozen=True)
class ManifestSource:
    path: Path
    source_path: str
    doc_key: str
    title: str
    doc_type: str
    platform: str
    version: str
    sheet: str | None = None
    header_rows: tuple[int, int] | None = None


def load_manifest(manifest_path: str | Path) -> list[ManifestSource]:
    path = Path(manifest_path)
    if not path.is_file():
        raise KnowledgeDBError(f"document manifest not found: {path}")
    text = _read_text_artifact(path)
    if text is None:
        raise KnowledgeDBError(f"document manifest is not a text file: {path}")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise KnowledgeDBError(f"invalid document manifest YAML: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise KnowledgeDBError("document manifest must contain a 'sources' list")

    sources = [_parse_source(item, index, path) for index, item in enumerate(payload["sources"], 1)]
    keys = [source.doc_key for source in sources]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise KnowledgeDBError(f"duplicate document doc_key values: {', '.join(duplicates)}")
    return sources


def _parse_source(item: Any, index: int, manifest_path: Path) -> ManifestSource:
    label = f"document manifest source {index}"
    if not isinstance(item, dict):
        raise KnowledgeDBError(f"{label} must be a mapping")
    missing = [field for field in _REQUIRED_FIELDS if not str(item.get(field) or "").strip()]
    if missing:
        raise KnowledgeDBError(f"{label} is missing required field(s): {', '.join(missing)}")

    doc_type = str(item["type"]).strip()
    if doc_type not in _DOC_TYPES:
        raise KnowledgeDBError(
            f"{label} has unsupported type {doc_type!r}; expected one of {sorted(_DOC_TYPES)}"
        )
    source_path = str(item["path"]).strip()
    resolved = _resolve_source_path(source_path, manifest_path)
    if not resolved.is_file():
        raise KnowledgeDBError(f"document source file not found: {source_path}")

    sheet = item.get("sheet")
    header_rows = item.get("header_rows")
    parsed_rows: tuple[int, int] | None = None
    if doc_type == "pinmux_template":
        if not (
            isinstance(header_rows, list)
            and len(header_rows) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) for value in header_rows)
            and 1 <= header_rows[0] <= header_rows[1]
        ):
            raise KnowledgeDBError(
                f"{label} pinmux_template requires header_rows: [start, end]"
            )
        parsed_rows = (header_rows[0], header_rows[1])
        if sheet is not None and not str(sheet).strip():
            sheet = None
    elif sheet is not None or header_rows is not None:
        raise KnowledgeDBError(f"{label} sheet/header_rows are valid only for pinmux_template")

    return ManifestSource(
        path=resolved,
        source_path=source_path,
        doc_key=str(item["doc_key"]).strip(),
        title=str(item["title"]).strip(),
        doc_type=doc_type,
        platform=str(item["platform"]).strip(),
        version=str(item["version"]).strip(),
        sheet=str(sheet).strip() if sheet is not None else None,
        header_rows=parsed_rows,
    )


def _resolve_source_path(source_path: str, manifest_path: Path) -> Path:
    candidate = Path(source_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (manifest_path.parent / candidate).resolve()
