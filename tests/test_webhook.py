import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent.config import Settings
from agent import run_lock
from agent.tools.github_tools import post_issue_comment
from agent.webhook import build_issue_text, extract_log_block, verify_signature


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature() -> None:
    body = b'{"action":"opened"}'
    signature = sign("secret", body)

    assert verify_signature("secret", body, signature)
    assert not verify_signature("secret", body, sign("wrong", body))
    assert not verify_signature("", body, signature)
    assert not verify_signature("secret", body, signature.removeprefix("sha256="))


def test_extract_log_block() -> None:
    body = "issue\n\n```text\nline 1\nline 2\n```\nmore"

    assert extract_log_block(body) == "line 1\nline 2"
    assert extract_log_block("no fence") is None
    assert extract_log_block(None) is None


def test_build_issue_text_tolerates_none() -> None:
    assert build_issue_text("Title", "Body") == "Title\n\nBody"
    assert build_issue_text("Title", None) == "Title"
    assert build_issue_text(None, "Body") == "Body"
    assert build_issue_text(None, None) == ""


def test_post_issue_comment_noops_without_url_or_token(monkeypatch) -> None:
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("httpx.post should not be called")

    monkeypatch.setattr("agent.tools.github_tools.httpx.post", fake_post)

    assert not post_issue_comment(None, "token", "body")
    assert not post_issue_comment("https://api.github.test/comments", "", "body")
    assert not called


def make_settings(tmp_path: Path, secret: str) -> Settings:
    return Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        GITHUB_WEBHOOK_SECRET=secret,
        GITHUB_TOKEN="",
        BSP_REPO_PATH=tmp_path / "repo",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
        AUTO_PUSH_ENABLED=False,
    )


def make_client(tmp_path: Path, monkeypatch, secret: str = "secret"):
    import agent.server as server

    monkeypatch.setattr(server, "settings", make_settings(tmp_path, secret))
    scheduled: list[tuple[str, str | None, str | None]] = []

    def fake_run_issue(issue_text: str, log_text: str | None, comments_url: str | None) -> None:
        scheduled.append((issue_text, log_text, comments_url))

    monkeypatch.setattr(server, "run_issue", fake_run_issue)
    return TestClient(server.app), scheduled


def post_webhook(
    client: TestClient,
    secret: str,
    payload: dict,
    event: str = "issues",
    delivery: str = "delivery-1",
):
    raw = json.dumps(payload).encode()
    return client.post(
        "/webhook/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": sign(secret, raw),
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "Content-Type": "application/json",
        },
    )


def test_health(tmp_path: Path, monkeypatch) -> None:
    client, _ = make_client(tmp_path, monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_github_webhook_issues_opened_schedules_run(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)
    payload = {
        "action": "opened",
        "issue": {
            "title": "camera failed",
            "body": "logs\n```text\ni2c -121\n```",
            "comments_url": "https://api.github.test/comments",
        },
    }

    response = post_webhook(client, "secret", payload)

    assert response.status_code == 202
    assert scheduled == [
        ("camera failed\n\nlogs\n```text\ni2c -121\n```", "i2c -121", "https://api.github.test/comments")
    ]


def test_github_webhook_bad_signature_is_unauthorized(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)
    raw = b'{"action":"opened","issue":{}}'

    response = client.post(
        "/webhook/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": sign("wrong", raw),
            "X-GitHub-Event": "issues",
        },
    )

    assert response.status_code == 401
    assert scheduled == []


def test_github_webhook_ignores_non_issue_events(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(client, "secret", {"action": "opened"}, event="push")

    assert response.status_code == 204
    assert scheduled == []


def test_github_webhook_ignores_non_opened_issue_actions(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(
        client,
        "secret",
        {"action": "edited", "issue": {"title": "camera", "body": ""}},
    )

    assert response.status_code == 204
    assert scheduled == []


def test_github_webhook_duplicate_delivery_does_not_schedule_twice(
    tmp_path: Path, monkeypatch
) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)
    payload = {
        "action": "opened",
        "issue": {"title": "camera", "body": "", "comments_url": "url"},
    }

    first = post_webhook(client, "secret", payload, delivery="same-delivery")
    second = post_webhook(client, "secret", payload, delivery="same-delivery")

    assert first.status_code == 202
    assert second.status_code == 200
    assert len(scheduled) == 1


def test_webhook_rejected_while_active(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)
    import agent.server as server

    assert run_lock.acquire_active(server.settings.runs_dir)
    payload = {
        "action": "opened",
        "issue": {"title": "camera", "body": "", "comments_url": "url"},
    }

    response = post_webhook(client, "secret", payload, delivery="blocked-delivery")

    assert response.status_code == 202
    assert scheduled == []
