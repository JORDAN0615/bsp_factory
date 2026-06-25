from __future__ import annotations

import httpx


def post_issue_comment(comments_url: str | None, token: str, body: str) -> bool:
    if not comments_url or not token:
        return False
    try:
        response = httpx.post(
            comments_url,
            json={"body": body},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True
