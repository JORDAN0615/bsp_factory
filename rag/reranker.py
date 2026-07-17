"""BGE CrossEncoder reranker.

Pre-loads the model so first query has no loading delay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

    from rag.models import Chunk

_model: "CrossEncoder | None" = None


def _get_model(model_name: str = "BAAI/bge-reranker-v2-m3") -> "CrossEncoder":
    global _model
    if _model is None:
        import torch
        from sentence_transformers import CrossEncoder
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = CrossEncoder(model_name, device=device)
    return _model


def prewarm():
    """Force load the reranker model (call once at startup)."""
    global _model
    if _model is None:
        try:
            _get_model()
        except ImportError:
            pass


def rerank(query: str, chunks: list["Chunk"], top_k: int = 5) -> list["Chunk"]:
    """Rerank chunks using cross-encoder scores.

    Returns top_k chunks sorted by score descending, with `score` field populated.
    The score is a sigmoid-normalised float from BGE-reranker (roughly 0-1).
    """
    if not chunks:
        return []

    try:
        model = _get_model()
    except ImportError:
        return chunks[:top_k]

    pairs = [(query, c.text) for c in chunks]
    raw_scores = model.predict(pairs, convert_to_numpy=True)
    score_list = raw_scores.tolist() if hasattr(raw_scores, "tolist") else list(raw_scores)

    scored = sorted(zip(chunks, score_list), key=lambda x: x[1], reverse=True)

    from dataclasses import replace
    return [replace(chunk, score=float(s)) for chunk, s in scored[:top_k]]
