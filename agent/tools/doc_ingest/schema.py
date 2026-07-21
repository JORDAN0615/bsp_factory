from __future__ import annotations

from typing import Any

from agent.tools.mic741_knowledge import _connect


DOC_SCHEMA_SQL = """
create table if not exists doc_sources (
  id uuid primary key,
  doc_key text not null unique,
  title text,
  doc_type text not null,
  platform text,
  doc_version text,
  source_path text not null,
  page_count int,
  content_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table doc_sources add column if not exists title text;

create table if not exists doc_chunks (
  id uuid primary key,
  source_id uuid not null references doc_sources(id) on delete cascade,
  chunk_type text not null,
  section_path text,
  page int,
  content text not null,
  symbols text[] not null default '{}',
  search_vector tsvector
);

create table if not exists pinmux_pins (
  id uuid primary key,
  source_id uuid not null references doc_sources(id) on delete cascade,
  platform text not null,
  ball text,
  signal_name text,
  columns jsonb not null default '{}',
  content text not null,
  symbols text[] not null default '{}',
  search_vector tsvector
);

create index if not exists doc_chunks_fts_idx on doc_chunks using gin(search_vector);
create index if not exists doc_chunks_symbols_idx on doc_chunks using gin(symbols);
create index if not exists doc_chunks_source_idx on doc_chunks(source_id);
create index if not exists pinmux_pins_fts_idx on pinmux_pins using gin(search_vector);
create index if not exists pinmux_pins_symbols_idx on pinmux_pins using gin(symbols);
create index if not exists pinmux_pins_platform_idx on pinmux_pins(platform);
create index if not exists pinmux_pins_signal_idx on pinmux_pins(signal_name);
"""


def init_doc_schema(db_url: str) -> None:
    with _connect(db_url) as conn:
        _execute_doc_schema(conn)


def _execute_doc_schema(conn: Any) -> None:
    for statement in [part.strip() for part in DOC_SCHEMA_SQL.split(";") if part.strip()]:
        conn.execute(statement)
