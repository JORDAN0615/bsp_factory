from rag.models import Chunk


def rrf(rank: int, k: int = 60) -> float:
    return 1 / (k + rank)


def merge(bm25_chunks: list[Chunk], vector_chunks: list[Chunk], top_k: int = 5) -> list[Chunk]:
    """RRF fusion — BM25 與 vector 結果以 chunk id 合併。"""
    scores: dict[str, float] = {}
    by_id: dict[str, Chunk] = {}

    for rank, chunk in enumerate(bm25_chunks):
        scores[chunk.id] = scores.get(chunk.id, 0) + rrf(rank)
        by_id[chunk.id] = chunk

    for rank, chunk in enumerate(vector_chunks):
        scores[chunk.id] = scores.get(chunk.id, 0) + rrf(rank)
        by_id[chunk.id] = chunk

    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [by_id[cid] for cid in ranked_ids[:top_k]]
