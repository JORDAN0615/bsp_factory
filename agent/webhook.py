from __future__ import annotations

import hashlib
import hmac
import re


_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    if not secret or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def extract_log_block(body: str | None) -> str | None:
    if body is None:
        return None
    match = _FENCE.search(body)
    if not match:
        return None
    return match.group(1).strip()


def build_issue_text(title: str | None, body: str | None) -> str:
    return f"{title or ''}\n\n{body or ''}".strip()
