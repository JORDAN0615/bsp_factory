"""Hybrid RAG pipeline — BM25 + Vector -> RRF Fusion.

Exports:
    hybrid_search_wide(query, top_k=20) -> list[Chunk]
        BM25 + dense vector -> RRF fusion, no reranker.
        Reranking is done once in hybrid_retrieve_node after merging all 3 DBs.
"""

from __future__ import annotations

from rag.bm25 import search as bm25_search
from rag.embedding import embed
from rag.hybrid import merge
from rag.models import Chunk
from rag.vector_store import COLLECTION, client


def _vector_search(query: str, top_k: int) -> list[Chunk]:
    response = client.query_points(
        collection_name=COLLECTION,
        query=embed(query),
        limit=top_k,
    )
    return [
        Chunk(
            id=point.payload["chunk_id"],
            text=point.payload["text"],
            source=point.payload["source"],
            section=point.payload.get("section", ""),
        )
        for point in response.points
    ]


def hybrid_search_wide(query: str, top_k: int = 20) -> list[Chunk]:
    """BM25 + dense vector -> RRF fusion. No reranker (done once in retrieve node)."""
    return merge(
        bm25_search(query, top_k=top_k),
        _vector_search(query, top_k=top_k),
        top_k=top_k,
    )
