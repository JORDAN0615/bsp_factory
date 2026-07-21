from rank_bm25 import BM25Okapi

from rag.models import Chunk

_bm25: BM25Okapi | None = None
_chunks: list[Chunk] = []


def build_bm25(chunks: list[Chunk]) -> None:
    global _bm25, _chunks

    _chunks = list(chunks)
    tokenized = [c.text.lower().split() for c in _chunks]
    _bm25 = BM25Okapi(tokenized)


def search(query: str, top_k: int = 5) -> list[Chunk]:
    if _bm25 is None or not _chunks:
        return []

    scores = _bm25.get_scores(query.lower().split())
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [_chunks[i] for i, _ in ranked[:top_k]]
