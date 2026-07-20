"""Retrieve node — selective 3-DB routing driven by Query Object fields.

Routing logic:
  semantic_query / keywords  → always query Qdrant (hybrid BM25 + dense)
  filters (model/version)    → also query PostgreSQL  (if DB available)
  graph_hints                → also query Neo4j        (if DB available)

All results are merged by RRF then reranked by Cross-Encoder (once only).
All three DB queries run in parallel via ThreadPoolExecutor.
"""

from __future__ import annotations

import concurrent.futures

from rag.config import DEBUG_RETRIEVAL, RETRIEVAL_TOP_K
from rag.rag_state import AgentState
from rag.models import Chunk
from rag.reranker import rerank as rerank_docs
from rag.retriever import hybrid_search_wide


def _query_qdrant(bm25_query: str, wide: int) -> list[Chunk]:
    return hybrid_search_wide(bm25_query, top_k=wide)


def _query_pg(filters: dict, keywords: list[str], wide: int) -> list[Chunk]:
    if not filters and not keywords:
        return []
    try:
        from db.postgres import query_by_filters, is_available
        if is_available():
            chunks = query_by_filters(filters, keywords=keywords, limit=wide)
            if DEBUG_RETRIEVAL:
                print(f"[POSTGRES] {len(chunks)} rows for filters={filters} keywords={keywords}")
            return chunks
    except Exception as e:
        if DEBUG_RETRIEVAL:
            print(f"[POSTGRES] skipped: {e}")
    return []


def _query_neo4j(graph_hints: list[str], keywords: list[str], wide: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        from db.neo4j_client import query_by_hints, query_by_error_keywords, is_available
        if is_available():
            if graph_hints:
                hint_chunks = query_by_hints(graph_hints, limit=wide)
                chunks.extend(hint_chunks)
                if DEBUG_RETRIEVAL:
                    print(f"[NEO4J] {len(hint_chunks)} paths for hints={graph_hints}")
            if keywords:
                kw_chunks = query_by_error_keywords(keywords, limit=wide)
                chunks.extend(kw_chunks)
                if DEBUG_RETRIEVAL:
                    print(f"[NEO4J] {len(kw_chunks)} paths for keywords={keywords}")
    except Exception as e:
        if DEBUG_RETRIEVAL:
            print(f"[NEO4J] skipped: {e}")
    return chunks


def hybrid_retrieve_node(state: AgentState) -> dict:
    qo = state.get("query_object", {})

    semantic_query = qo.get("semantic_query") or state.get("original_input", "")
    keywords       = qo.get("keywords", [])
    filters        = qo.get("filters", {})
    graph_hints    = qo.get("graph_hints", [])

    bm25_query = semantic_query
    if keywords:
        bm25_query = semantic_query + " " + " ".join(keywords)

    WIDE = max(RETRIEVAL_TOP_K * 4, 20)

    # ── Query all three DBs in parallel ──────────────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_qdrant = executor.submit(_query_qdrant, bm25_query, WIDE)
        f_pg     = executor.submit(_query_pg,     filters, keywords, WIDE)
        f_neo    = executor.submit(_query_neo4j,  graph_hints, keywords, WIDE)

        qdrant_chunks: list[Chunk] = f_qdrant.result()
        pg_chunks:     list[Chunk] = f_pg.result()
        neo_chunks:    list[Chunk] = f_neo.result()

    # ── Merge + deduplicate ───────────────────────────────────────────────────
    seen:   set[str]  = set()
    deduped: list[Chunk] = []
    for c in qdrant_chunks + pg_chunks + neo_chunks:
        if c.id not in seen:
            seen.add(c.id)
            deduped.append(c)

    # ── Single rerank pass ────────────────────────────────────────────────────
    reranked   = rerank_docs(semantic_query, deduped, top_k=RETRIEVAL_TOP_K)
    crag_score = reranked[0].score if reranked else 0.0

    if DEBUG_RETRIEVAL:
        print("\n========== Retrieval Debug ==========")
        print(f"semantic_query : {semantic_query!r}")
        print(f"keywords       : {keywords}")
        print(f"filters        : {filters}")
        print(f"graph_hints    : {graph_hints}")
        print(f"pool           : qdrant={len(qdrant_chunks)} pg={len(pg_chunks)} neo4j={len(neo_chunks)} → {len(deduped)} unique")
        print(f"\nReranked top-{len(reranked)}:")
        for i, chunk in enumerate(reranked, 1):
            preview = chunk.text.replace("\n", " ")[:100]
            preview_safe = preview.encode("ascii", errors="replace").decode("ascii")
            print(f"  [{i}] score={chunk.score:.3f} [{chunk.source}/{chunk.section}] {preview_safe}...")
        print(f"\ncrag_score (top-1): {crag_score:.3f}")
        print("=====================================\n")

    return {
        "candidates":       deduped,
        "reranked_results": reranked,
        "crag_score":       crag_score,
    }
