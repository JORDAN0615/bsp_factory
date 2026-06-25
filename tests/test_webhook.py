import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent import run_lock
from agent.config import Settings
from agent.tools.gitlab_tools import post_issue_note
from agent.webhook import build_issue_text, build_notes_url, extract_log_block, verify_token


def test_verify_token() -> None:
    assert verify_token("secret", "secret")
    assert not verify_token("", "secret")
    assert not verify_token("secret", "wrong")


def test_build_notes_url() -> None:
    assert (
        build_notes_url("https://gitlab.com/api/v4", 42, 7)
        == "https://gitlab.com/api/v4/projects/42/issues/7/notes"
    )
    assert (
        build_notes_url("https://gitlab.example/api/v4/", "group%2Frepo", "3")
        == "https://gitlab.example/api/v4/projects/group%2Frepo/issues/3/notes"
    )


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


def test_post_issue_note_noops_without_url_or_token(monkeypatch) -> None:
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("httpx.post should not be called")

    monkeypatch.setattr("agent.tools.gitlab_tools.httpx.post", fake_post)

    assert not post_issue_note(None, "token", "body")
    assert not post_issue_note("https://gitlab.example/api/v4/projects/42/issues/7/notes", "", "body")
    assert not called


def make_settings(tmp_path: Path, token: str) -> Settings:
    return Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        GITLAB_WEBHOOK_TOKEN=token,
        GITLAB_TOKEN="",
        GITLAB_API_URL="https://gitlab.example/api/v4",
        BSP_REPO_PATH=tmp_path / "repo",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
        AUTO_PUSH_ENABLED=False,
    )


def make_client(tmp_path: Path, monkeypatch, token: str = "secret"):
    import agent.server as server

    monkeypatch.setattr(server, "settings", make_settings(tmp_path, token))
    scheduled: list[tuple[str, str | None, str | None]] = []

    def fake_run_issue(issue_text: str, log_text: str | None, notes_url: str | None) -> None:
        scheduled.append((issue_text, log_text, notes_url))

    monkeypatch.setattr(server, "run_issue", fake_run_issue)
    return TestClient(server.app), scheduled


def gitlab_issue_payload(action: str = "open") -> dict:
    return {
        "object_kind": "issue",
        "object_attributes": {
            "action": action,
            "title": "camera failed",
            "description": "logs\n```text\ni2c -121\n```",
            "iid": 7,
        },
        "project": {"id": 42},
    }


def post_webhook(
    client: TestClient,
    token: str,
    payload: dict,
    event: str = "Issue Hook",
    delivery: str = "delivery-1",
):
    raw = json.dumps(payload).encode()
    return client.post(
        "/webhook/github",
        content=raw,
        headers={
            "X-Gitlab-Token": token,
            "X-Gitlab-Event": event,
            "X-Gitlab-Event-UUID": delivery,
            "Content-Type": "application/json",
        },
    )


def test_health(tmp_path: Path, monkeypatch) -> None:
    client, _ = make_client(tmp_path, monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_gitlab_webhook_issue_open_schedules_run(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(client, "secret", gitlab_issue_payload())

    assert response.status_code == 202
    assert scheduled == [
        (
            "camera failed\n\nlogs\n```text\ni2c -121\n```",
            "i2c -121",
            "https://gitlab.example/api/v4/projects/42/issues/7/notes",
        )
    ]


def test_gitlab_webhook_bad_token_is_unauthorized(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(client, "wrong", gitlab_issue_payload())

    assert response.status_code == 401
    assert scheduled == []


def test_gitlab_webhook_ignores_non_issue_hook_events(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(client, "secret", gitlab_issue_payload(), event="Push Hook")

    assert response.status_code == 204
    assert scheduled == []


def test_gitlab_webhook_ignores_non_issue_payloads(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(client, "secret", {"object_kind": "merge_request"})

    assert response.status_code == 204
    assert scheduled == []


def test_gitlab_webhook_ignores_non_open_actions(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)

    response = post_webhook(client, "secret", gitlab_issue_payload(action="update"))

    assert response.status_code == 204
    assert scheduled == []


def test_gitlab_webhook_duplicate_event_uuid_does_not_schedule_twice(
    tmp_path: Path, monkeypatch
) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)
    payload = gitlab_issue_payload()

    first = post_webhook(client, "secret", payload, delivery="same-delivery")
    second = post_webhook(client, "secret", payload, delivery="same-delivery")

    assert first.status_code == 202
    assert second.status_code == 200
    assert len(scheduled) == 1


def test_webhook_rejected_while_active(tmp_path: Path, monkeypatch) -> None:
    client, scheduled = make_client(tmp_path, monkeypatch)
    import agent.server as server

    assert run_lock.acquire_active(server.settings.runs_dir)

    response = post_webhook(client, "secret", gitlab_issue_payload(), delivery="blocked-delivery")

    assert response.status_code == 409
    assert scheduled == []
