__all__ = ["embed"]

import torch
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = SentenceTransformer(
            "BAAI/bge-m3",
            device=device,
            model_kwargs={"torch_dtype": torch.float16},
        )
    return _model


def embed(text: str) -> list:
    return _get_model().encode(text).tolist()


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    return _get_model().encode(texts, batch_size=batch_size, show_progress_bar=True).tolist()
