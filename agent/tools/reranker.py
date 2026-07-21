from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from agent.config import Settings


logger = logging.getLogger(__name__)

_WARNED: set[str] = set()

# The cross-encoder judges relevance from the head of a passage; feeding it more
# is wasted work, and oversized input is fatal rather than degraded. Case
# candidates concatenate issue text with a whole git patch, which has reached
# 85k tokens in practice and made llama-server reject the batch with HTTP 500.
# Roughly 2000 characters is ~500 tokens, which keeps every document well inside
# the server's physical batch even when many are sent at once.
_MAX_DOC_CHARS = 2000


def _warn_once(endpoint: str, message: str) -> None:
    if endpoint in _WARNED:
        return
    _WARNED.add(endpoint)
    logger.warning("cross-encoder reranker unavailable; using ts_rank order: %s", message)


def _sigmoid(logit: float) -> float:
    """Convert llama.cpp's raw reranker logit to the existing [0, 1] scale."""
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp_logit = math.exp(logit)
    return exp_logit / (1.0 + exp_logit)


def _parse_results(data: Any, document_count: int) -> list[tuple[int, float]]:
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("reranker response is missing a results list")
    results = data["results"]
    if len(results) != document_count:
        raise ValueError(
            f"reranker returned {len(results)} results for {document_count} documents"
        )

    parsed: list[tuple[int, float]] = []
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("reranker result must be an object")
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("reranker result index must be an integer")
        if index < 0 or index >= document_count or index in seen:
            raise ValueError(f"reranker returned invalid or duplicate index {index}")
        try:
            logit = float(item["relevance_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("reranker relevance_score must be numeric") from exc
        if not math.isfinite(logit):
            raise ValueError("reranker relevance_score must be finite")
        seen.add(index)
        parsed.append((index, _sigmoid(logit)))
    return parsed


def rerank(
    query: str,
    documents: list[str],
    top_k: int,
    settings: "Settings",
) -> list[tuple[int, float | None]]:
    """Rank documents through the local llama.cpp reranker, failing open to ts_rank."""
    keep = min(max(top_k, 0), len(documents))
    fallback = [(index, None) for index in range(keep)]
    if not documents or keep == 0:
        return fallback

    endpoint = settings.reranker_url
    payload_documents = [document[:_MAX_DOC_CHARS] for document in documents]
    try:
        response = httpx.post(
            endpoint,
            json={"query": query, "documents": payload_documents},
            headers={"Content-Type": "application/json"},
            timeout=settings.reranker_timeout_sec,
        )
        response.raise_for_status()
        ranked = _parse_results(response.json(), len(documents))
    except Exception as exc:  # noqa: BLE001 - retrieval must never break the agent loop
        _warn_once(endpoint, str(exc))
        return fallback

    return sorted(ranked, key=lambda item: item[1], reverse=True)[:keep]
