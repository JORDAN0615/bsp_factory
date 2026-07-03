"""Remote KB client for BSP RAG integration.

Configure KB_API_URL in .env to point at the server's KB endpoint.
When KB_API_URL is not set, query() returns an empty list and the RAG
falls through to gap mode (LLM answers from own knowledge).

Expected server API contract:
    POST {KB_API_URL}/query
    Request:  {"query": str, "top_k": int}
    Response: {"chunks": [{"id": str, "text": str, "source": str, "section": str}]}
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class KBChunk:
    id: str
    text: str
    source: str
    section: str = ""
    score: float = 0.0


class KBClient:
    def __init__(self) -> None:
        self._base_url = (os.getenv("KB_API_URL") or "").rstrip("/")
        self._timeout = int(os.getenv("KB_API_TIMEOUT", "10"))

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def query(self, query: str, top_k: int = 20) -> list[KBChunk]:
        """Query the remote KB. Returns [] if KB_API_URL is not configured."""
        if not self._base_url:
            return []
        url = f"{self._base_url}/query"
        body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[KB_CLIENT] query failed: {exc}")
            return []
        return [
            KBChunk(
                id=c.get("id", f"chunk_{i}"),
                text=c.get("text", ""),
                source=c.get("source", ""),
                section=c.get("section", ""),
            )
            for i, c in enumerate(data.get("chunks", []))
        ]
