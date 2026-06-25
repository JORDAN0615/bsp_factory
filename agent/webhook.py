from __future__ import annotations

import hmac
import re


_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def verify_token(expected: str, header_token: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(expected, header_token)


def extract_log_block(body: str | None) -> str | None:
    if body is None:
        return None
    match = _FENCE.search(body)
    if not match:
        return None
    return match.group(1).strip()


def build_issue_text(title: str | None, body: str | None) -> str:
    return f"{title or ''}\n\n{body or ''}".strip()


def build_notes_url(api_url: str, project_id, issue_iid) -> str:
    return f"{api_url.rstrip('/')}/projects/{project_id}/issues/{issue_iid}/notes"
