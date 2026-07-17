__all__ = ["embed"]

import os
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None

_MODEL_ID = "BAAI/bge-m3"


def _resolve_model_path() -> str:
    """Return local cache path when offline so backend_should_export skips Hub calls."""
    if not (os.getenv("HF_HUB_OFFLINE") or os.getenv("TRANSFORMERS_OFFLINE")):
        return _MODEL_ID
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(_MODEL_ID, local_files_only=True)
    except Exception:
        return _MODEL_ID


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from pathlib import Path

        # ONNX Runtime backend: 5-10x faster than PyTorch CPU, no GPU required.
        # First call exports the model to ONNX (~46s), subsequent loads are instant.
        model_path = _resolve_model_path()
        _model = SentenceTransformer(model_path, backend="onnx")
        # Truncate to 512 tokens; longer texts cause OOM in ONNX attention matrix.
        _model.max_seq_length = 512

        # Persist ONNX weights so next load is instant (skips re-export).
        if Path(model_path).exists() and not list(Path(model_path).rglob("*.onnx")):
            _model.save_pretrained(model_path)
    return _model


def embed(text: str) -> list:
    return _get_model().encode(text).tolist()


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    return _get_model().encode(texts, batch_size=batch_size, show_progress_bar=True).tolist()
