import os
from pathlib import Path

from rag.bm25 import build_bm25
from rag.embedding import embed_batch
from rag.loader import load_chunks
from rag.models import Chunk
from rag.vector_store import COLLECTION, client, init_collection
from rag.cache import load_index_from_cache, save_index_to_cache

from qdrant_client.models import PointStruct


def build_index(*, force: bool = False) -> list[Chunk]:
    """Load or build index.

    On first run: loads KB files -> embeds -> builds BM25 -> upserts Qdrant.
    On subsequent runs: if cache is valid, skips embedding entirely.
    Vectors are restored from cache into Qdrant (fast, ~2s).

    Configure KB location via KB_DIR env var (default: MIC-741_KnowledgeBase).

    Args:
        force: if True, always rebuild regardless of cache state.
    """
    kb_dir = Path(__file__).parent.parent / os.getenv("KB_DIR", "MIC-741_KnowledgeBase")
    cached = load_index_from_cache()

    if cached and not force:
        # --- Fast path: cache valid, skip embedding ---
        chunks = load_chunks()
        print(f"Loaded {len(chunks)} chunks from cache")

        # BM25 tokenization is fast (O(n) string split)
        build_bm25(chunks)

        # If Qdrant already has the right number of points (persisted on disk),
        # skip the upsert entirely — no need to re-push vectors we already have.
        try:
            existing = client.count(collection_name=COLLECTION).count
            if existing == len(chunks):
                print(f"[FAST] Restored {len(chunks)} chunks from cache (skipped embedding + upsert)")
                return chunks
        except Exception:
            pass

        # Initialize collection if missing (fresh Qdrant)
        cached_vectors = cached.get("vectors")
        if cached_vectors:
            embed_dim = len(cached_vectors[0])
            init_collection(embed_dim)

        # Restore vectors directly from cache
        if cached_vectors and len(cached_vectors) == len(chunks):
            points = [
                PointStruct(
                    id=i,
                    vector=vec,
                    payload={
                        "chunk_id": c.id,
                        "text": c.text,
                        "source": c.source,
                        "section": c.section,
                    },
                )
                for i, (c, vec) in enumerate(zip(chunks, cached_vectors))
            ]
            client.upsert(collection_name=COLLECTION, points=points)
            print(f"[FAST] Restored {len(chunks)} chunks from cache (skipped embedding)")
            return chunks
        else:
            print("[WARN] Cache vector count mismatch, rebuilding...")

    # --- Slow path: rebuild everything (includes embedding model load) ---
    chunks = load_chunks()
    if not chunks:
        print("[WARN] No knowledge chunks found")
        return []

    # Build BM25 (fast)
    build_bm25(chunks)

    # If Qdrant already has the right vectors (from a previous run), skip re-embedding.
    # This handles the case where the cache checksum function changed but KB content
    # did not actually change — just refresh the checksum and reuse existing vectors.
    if not force:
        try:
            existing = client.count(collection_name=COLLECTION).count
            if existing == len(chunks):
                from rag.cache import refresh_checksum
                if refresh_checksum(kb_dir):
                    print(f"[SMART] {len(chunks)} chunks already in Qdrant — refreshed cache checksum, skipped embedding")
                    return chunks
        except Exception:
            pass

    # Generate embeddings in batches (batch_size=8 to avoid GPU OOM on 4GB VRAM)
    vectors = embed_batch([c.text for c in chunks], batch_size=8)

    # Init + upsert into Qdrant
    init_collection(len(vectors[0]))
    points = [
        PointStruct(
            id=i,
            vector=v,
            payload={
                "chunk_id": c.id,
                "text": c.text,
                "source": c.source,
                "section": c.section,
            },
        )
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]
    client.upsert(collection_name=COLLECTION, points=points)

    # Save to cache for next startup
    save_index_to_cache(chunks, vectors, kb_dir)

    # Ingest structured data into PostgreSQL + Neo4j (if available)
    try:
        from db.postgres import is_available as pg_ok
        from db.neo4j_client import is_available as neo4j_ok
        from db.ingestion import run_ingestion
        _pg, _neo = pg_ok(), neo4j_ok()
        if _pg or _neo:
            print(f"[DB] Ingesting KB → PostgreSQL={'✓' if _pg else '✗'} Neo4j={'✓' if _neo else '✗'}")
            run_ingestion(_pg, _neo)
    except Exception as exc:
        print(f"[DB] Ingestion skipped: {exc}")

    print(f"[OK] Indexed {len(points)} chunks (BM25 + Vector)")
    return chunks
