from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source: str
    section: str = ""
    score: float = 0.0  # reranker cross-encoder score (0-1); 0 = not yet scored
