from __future__ import annotations

import httpx


def post_issue_note(notes_url: str | None, token: str, body: str) -> bool:
    if not notes_url or not token:
        return False
    try:
        response = httpx.post(
            notes_url,
            json={"body": body},
            headers={"PRIVATE-TOKEN": token},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True
