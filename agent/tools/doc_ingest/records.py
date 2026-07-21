from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.tools.doc_ingest.manifest import ManifestSource, load_manifest
from agent.tools.doc_ingest.schema import _execute_doc_schema
from agent.tools.mic741_knowledge import KnowledgeDBError, _connect


@dataclass(frozen=True)
class ChunkRecord:
    chunk_type: str
    content: str
    section_path: str | None = None
    page: int | None = None
    symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PinRecord:
    platform: str
    columns: dict[str, Any]
    content: str
    ball: str | None = None
    signal_name: str | None = None
    symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IngestedRecords:
    page_count: int | None = None
    chunks: list[ChunkRecord] = field(default_factory=list)
    pins: list[PinRecord] = field(default_factory=list)


def ingest_documents(
    manifest_path: str | Path,
    db_url: str,
    *,
    force: bool = False,
) -> dict[str, int]:
    sources = load_manifest(manifest_path)
    stats = {"sources": 0, "chunks": 0, "pins": 0, "skipped": 0}
    with _connect(db_url) as conn:
        _execute_doc_schema(conn)
        for source in sources:
            content_hash = _content_hash(source.path)
            if not force and _stored_hash(conn, source.doc_key) == content_hash:
                stats["skipped"] += 1
                continue
            records = _ingest_source(source)
            _replace_source(conn, source, content_hash, records)
            stats["sources"] += 1
            stats["chunks"] += len(records.chunks)
            stats["pins"] += len(records.pins)
    return stats


def _content_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ingest_source(source: ManifestSource) -> IngestedRecords:
    try:
        if source.doc_type == "pinmux_template":
            from agent.tools.doc_ingest.pinmux_xlsm import ingest_pinmux

            return ingest_pinmux(source)
        from agent.tools.doc_ingest.pdf_docs import ingest_pdf

        return ingest_pdf(source)
    except KnowledgeDBError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeDBError(f"failed to ingest {source.source_path}: {exc}") from exc


def _stored_hash(conn: Any, doc_key: str) -> str | None:
    row = conn.execute(
        "select content_hash from doc_sources where doc_key = %s",
        (doc_key,),
    ).fetchone()
    return str(row[0]) if row else None


def _replace_source(
    conn: Any,
    source: ManifestSource,
    content_hash: str,
    records: IngestedRecords,
) -> None:
    from psycopg.types.json import Jsonb

    source_id = uuid.uuid5(uuid.NAMESPACE_URL, f"bsp-agent:doc:{source.doc_key}")
    conn.execute("delete from doc_sources where doc_key = %s", (source.doc_key,))
    conn.execute(
        """
        insert into doc_sources (
          id, doc_key, title, doc_type, platform, doc_version, source_path,
          page_count, content_hash, updated_at
        ) values (
          %(id)s, %(doc_key)s, %(title)s, %(doc_type)s, %(platform)s,
          %(doc_version)s, %(source_path)s, %(page_count)s, %(content_hash)s, now()
        )
        """,
        {
            "id": source_id,
            "doc_key": source.doc_key,
            "title": source.title,
            "doc_type": source.doc_type,
            "platform": source.platform,
            "doc_version": source.version,
            "source_path": source.source_path,
            "page_count": records.page_count,
            "content_hash": content_hash,
        },
    )
    for chunk in records.chunks:
        conn.execute(
            """
            insert into doc_chunks (
              id, source_id, chunk_type, section_path, page, content, symbols,
              search_vector
            ) values (
              %(id)s, %(source_id)s, %(chunk_type)s, %(section_path)s, %(page)s,
              %(content)s, %(symbols)s, to_tsvector('simple', %(content)s)
            )
            """,
            {
                "id": uuid.uuid4(),
                "source_id": source_id,
                "chunk_type": chunk.chunk_type,
                "section_path": chunk.section_path,
                "page": chunk.page,
                "content": chunk.content,
                "symbols": chunk.symbols,
            },
        )
    for pin in records.pins:
        conn.execute(
            """
            insert into pinmux_pins (
              id, source_id, platform, ball, signal_name, columns, content,
              symbols, search_vector
            ) values (
              %(id)s, %(source_id)s, %(platform)s, %(ball)s, %(signal_name)s,
              %(columns)s, %(content)s, %(symbols)s,
              to_tsvector('simple', %(content)s)
            )
            """,
            {
                "id": uuid.uuid4(),
                "source_id": source_id,
                "platform": pin.platform,
                "ball": pin.ball,
                "signal_name": pin.signal_name,
                "columns": Jsonb(pin.columns),
                "content": pin.content,
                "symbols": pin.symbols,
            },
        )
