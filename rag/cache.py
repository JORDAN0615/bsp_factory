"""Cache vector embeddings and BM25 index to disk.

On startup, attempts to restore cached state so that embedding model
and BM25 rebuild are skipped entirely (cold-start from ~50s to <3s).

Cache layout (inside project dir):
    .cache/index_v1.pkl      -- Chunk ids/texts, tokenized BM25 tokens, embeddings
    _qdrant/                 -- Qdrant native persistent storage

Usage::

    save_index_to_cache(chunks, vectors, bm25_tokens, knowledge_dir, mock_data_dir)
    cached = load_index_from_cache()
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

CACHE_VERSION = 1
CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "index_v1.pkl"
INGESTION_SENTINEL = CACHE_DIR / "ingestion_v1.json"


# -- checksum helpers -------------------------------------------------

_SOURCE_EXTENSIONS = {'.c', '.h', '.cpp', '.dtsi', '.dts', '.sh', '.mk', '.yaml', '.yml'}
_SOURCE_PATTERNS   = {"02_Original_Code/*/before/**/*", "02_Original_Code/*/after/**/*"}


def _data_checksum(kb_dir: Path) -> str:
    """MD5 of all indexed KB files (md + patch + source + corpus + pdf + excel)."""
    h = hashlib.md5()
    patterns = [
        "01_Issues/*.md",
        "02_Original_Code/*/PROMPT.md",
        "02_Original_Code/**/*.patch",
        "02_Original_Code/**/*.diff",
        "02_Original_Code/*/before/**/*",
        "02_Original_Code/*/after/**/*",
        "03_Git_History/*.md",
        "03_Git_History/patches/*.patch",
        "corpus/**/*.md",
        "material/*.pdf",
        "material/*.xls*",
    ]
    if kb_dir.exists():
        for pattern in patterns:
            for f in sorted(kb_dir.glob(pattern)):
                if not f.is_file():
                    continue
                # Source dirs: only hash files that are actually indexed
                if pattern in _SOURCE_PATTERNS and f.suffix.lower() not in _SOURCE_EXTENSIONS:
                    continue
                try:
                    h.update(f.stat().st_size.to_bytes(8, "little"))
                    h.update(f.read_bytes())
                except OSError:
                    pass
    return h.hexdigest()


# -- cache save / load ------------------------------------------------

def save_index_to_cache(
    chunks: list,
    vectors: list,
    kb_dir: Path,
) -> None:
    """Persist chunks + vectors + BM25 tokens for next startup."""
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        from rag.bm25 import _chunks as bm25_chunks
        bm25_tokens = [c.text.lower().split() for c in bm25_chunks] if bm25_chunks else []
    except Exception:
        bm25_tokens = []

    payload = {
        "version": CACHE_VERSION,
        "checksum": _data_checksum(kb_dir),
        "n_chunks": len(chunks),
        "vectors": vectors,
        "bm25_tokens": bm25_tokens,
    }
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"[WARN] Failed to save cache: {e}")


def refresh_checksum(kb_dir: Path) -> bool:
    """Recalculate checksum and save it back without re-embedding.

    Call this when the checksum function itself changed but KB content is the same.
    Returns True if successful.
    """
    if not CACHE_FILE.is_file():
        return False
    try:
        with open(CACHE_FILE, "rb") as f:
            payload = pickle.load(f)
        if payload.get("version") != CACHE_VERSION:
            return False
        payload["checksum"] = _data_checksum(kb_dir)
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        return True
    except Exception as e:
        print(f"[WARN] refresh_checksum failed: {e}")
        return False


def ingestion_done_for(kb_dir: Path) -> bool:
    """Return True if DB ingestion was already completed for this KB checksum."""
    if not INGESTION_SENTINEL.is_file():
        return False
    try:
        import json
        data = json.loads(INGESTION_SENTINEL.read_text(encoding="utf-8"))
        return data.get("checksum") == _data_checksum(kb_dir)
    except Exception:
        return False


def mark_ingestion_done(kb_dir: Path) -> None:
    """Write sentinel so next startup skips re-ingestion for unchanged KB."""
    import json
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        INGESTION_SENTINEL.write_text(
            json.dumps({"checksum": _data_checksum(kb_dir)}),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[WARN] Failed to save ingestion sentinel: {e}")


def load_index_from_cache() -> dict | None:
    """Try restoring cached index.

    Returns dict with ``{n_chunks, vectors, bm25_tokens, checksum}`` or
    ``None`` if cache is stale / missing / corrupted.
    """
    if not CACHE_FILE.is_file():
        return None

    try:
        with open(CACHE_FILE, "rb") as f:
            payload = pickle.load(f)
    except Exception:
        return None

    # Version check
    if payload.get("version") != CACHE_VERSION:
        return None

    # Checksum check
    import os
    kb_path = Path(__file__).parent.parent / os.getenv("KB_DIR", "MIC-741_KnowledgeBase")
    stored_cs = payload.get("checksum", "?")
    current_cs = _data_checksum(kb_path)
    if stored_cs != current_cs:
        print(f"[CACHE] Checksum mismatch: stored={stored_cs[:12]}... != current={current_cs[:12]}...")
        return None

    if not payload.get("n_chunks") or not payload.get("vectors"):
        return None

    return dict(
        n_chunks=payload["n_chunks"],
        vectors=payload["vectors"],
        bm25_tokens=payload.get("bm25_tokens"),
        checksum=current_cs,
    )
