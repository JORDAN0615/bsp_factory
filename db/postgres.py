"""PostgreSQL client — schema management, ingestion helpers, and filter-based retrieval.

Provides:
  init_schema()            — create tables (idempotent)
  query_by_filters(...)    — translate Query Object `filters` to SQL WHERE
  insert_case(...)         — upsert a bsp_case row
  insert_gap_report(...)   — write a knowledge-gap entry to review_queue
"""

from __future__ import annotations

import json
import os
from typing import Any

from rag.models import Chunk

POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://bsp:bsp_secret@localhost:5432/bsp_agent"
)


def _get_conn():
    import psycopg2
    return psycopg2.connect(POSTGRES_URL)


def is_available() -> bool:
    try:
        conn = _get_conn()
        conn.close()
        return True
    except Exception:
        return False


# ── Schema ────────────────────────────────────────────────────────────────────

def init_schema() -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bsp_cases (
                    id           SERIAL PRIMARY KEY,
                    model        VARCHAR(50),
                    bsp_version  VARCHAR(20),
                    component    VARCHAR(50),
                    test_item    VARCHAR(100),
                    category     VARCHAR(50),
                    status       VARCHAR(20),
                    error_code   VARCHAR(50),
                    error_msg    TEXT,
                    fix_summary  TEXT,
                    verified     BOOLEAN DEFAULT FALSE,
                    source       VARCHAR(20),
                    date         DATE,
                    source_ref   VARCHAR(200),
                    UNIQUE (source_ref)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS review_queue (
                    id          SERIAL PRIMARY KEY,
                    type        VARCHAR(20),
                    content     JSONB,
                    status      VARCHAR(20) DEFAULT 'pending',
                    created_at  TIMESTAMP DEFAULT NOW(),
                    resolved_at TIMESTAMP
                );
            """)
        conn.commit()


# ── Ingestion ─────────────────────────────────────────────────────────────────

def insert_case(case: dict[str, Any]) -> None:
    """Upsert a BSP case. Skips if source_ref already exists."""
    sql = """
        INSERT INTO bsp_cases
            (model, bsp_version, component, test_item, category, status,
             error_code, error_msg, fix_summary, verified, source, date, source_ref)
        VALUES
            (%(model)s, %(bsp_version)s, %(component)s, %(test_item)s, %(category)s,
             %(status)s, %(error_code)s, %(error_msg)s, %(fix_summary)s,
             %(verified)s, %(source)s, %(date)s, %(source_ref)s)
        ON CONFLICT (source_ref) DO NOTHING
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, case)
        conn.commit()


def insert_gap_report(report: dict) -> None:
    sql = "INSERT INTO review_queue (type, content) VALUES ('knowledge_gap', %s)"
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (json.dumps(report),))
        conn.commit()


# ── Retrieval ─────────────────────────────────────────────────────────────────

_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    try:
        init_schema()
        _schema_ready = True
    except Exception:
        pass


def query_by_filters(
    filters: dict,
    keywords: list[str] | None = None,
    limit: int = 20,
) -> list[Chunk]:
    """Translate Query Object filters + keywords → SQL WHERE → list[Chunk].

    filters: structured fields (model, bsp_version, component, status)
    keywords: error signatures / free-text terms — matched against error_msg and fix_summary
    """
    conditions: list[str] = []
    params: list[Any] = []

    if filters.get("model"):
        conditions.append("model ILIKE %s")
        params.append(f"%{filters['model']}%")
    if filters.get("bsp_version"):
        conditions.append("bsp_version ILIKE %s")
        params.append(f"%{filters['bsp_version']}%")
    if filters.get("status"):
        conditions.append("status = %s")
        params.append(filters["status"].upper())
    if filters.get("component"):
        conditions.append("component ILIKE %s")
        params.append(f"%{filters['component']}%")

    # Error keyword search: any keyword matches error_msg OR fix_summary
    if keywords:
        kw_clauses: list[str] = []
        for kw in keywords:
            kw_clauses.append("(error_msg ILIKE %s OR fix_summary ILIKE %s)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        conditions.append(f"({' OR '.join(kw_clauses)})")

    if not conditions:
        return []

    where = " AND ".join(conditions)
    sql = f"SELECT * FROM bsp_cases WHERE {where} ORDER BY id DESC LIMIT %s"
    params.append(limit)

    _ensure_schema()
    try:
        from psycopg2.extras import RealDictCursor
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_row_to_chunk(dict(r)) for r in rows]
    except Exception as e:
        print(f"[POSTGRES] query_by_filters error: {e}")
        return []


def _row_to_chunk(row: dict) -> Chunk:
    """Serialize a PostgreSQL row to a text Chunk for the Reranker."""
    parts: list[str] = []
    if row.get("model"):
        parts.append(f"Model: {row['model']}")
    if row.get("bsp_version"):
        parts.append(f"BSP: {row['bsp_version']}")
    if row.get("component"):
        parts.append(f"Component: {row['component']}")
    if row.get("status"):
        parts.append(f"Status: {row['status']}")
    if row.get("error_code"):
        parts.append(f"Error code: {row['error_code']}")
    if row.get("error_msg"):
        parts.append(f"Error: {row['error_msg']}")
    if row.get("fix_summary"):
        parts.append(f"Fix: {row['fix_summary']}")
    text = " | ".join(parts)
    return Chunk(
        id=f"pg_{row['id']}",
        text=text,
        source="postgresql",
        section=row.get("component", ""),
    )
