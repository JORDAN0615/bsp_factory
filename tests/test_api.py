from pathlib import Path

from fastapi.testclient import TestClient

from agent.config import Settings
from agent.state import BSPAgentState, RepairAttempt
from agent.tools.artifact_tools import attempt_dir


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
    )


def make_client(tmp_path: Path, monkeypatch) -> TestClient:
    import agent.server as server

    monkeypatch.setattr(server, "settings", make_settings(tmp_path))
    return TestClient(server.app)


def write_state(tmp_path: Path, run_id: str = "run123", stage: str = "human_review") -> BSPAgentState:
    run_dir = tmp_path / "runs" / run_id
    state = BSPAgentState(
        run_id=run_id,
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        stage=stage,
        issue="camera probe failed",
        attempts=[
            RepairAttempt(
                attempt_no=1,
                changed_files=["board-camera.dts"],
                code_review_decision="pass",
            )
        ],
    )
    state.save()
    return state


def test_api_runs_returns_pending_runs(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    rows = [{"run_id": "run123", "stage": "human_review"}]
    monkeypatch.setattr(server, "list_pending_runs", lambda settings: rows)

    response = client.get("/api/runs")

    assert response.status_code == 200
    assert response.json() == rows


def test_api_run_detail_missing_returns_404(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/api/runs/missing")

    assert response.status_code == 404


def test_api_run_detail_returns_state_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    state = write_state(tmp_path)
    artifacts = attempt_dir(state.run_dir, 1)
    (artifacts / "patch.md").write_text("diff text", encoding="utf-8")
    (artifacts / "code_review.md").write_text("review text", encoding="utf-8")
    (artifacts / "repo_inspection.md").write_text("inspection text", encoding="utf-8")

    response = client.get("/api/runs/run123")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run123",
        "stage": "human_review",
        "issue": "camera probe failed",
        "attempt_no": 1,
        "changed_files": ["board-camera.dts"],
        "publish_error": None,
        "code_review": "review text",
        "diff": "diff text",
        "repo_inspection": "inspection text",
    }


def test_api_approve_calls_workflow_and_returns_state(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    write_state(tmp_path)
    approved = write_state(tmp_path, stage="published")
    approved.current_attempt.published_branch = "bsp-agent/run123"
    approved.current_attempt.changed_files = ["board-camera.dts"]
    called = {}

    def fake_approve_run(run_dir, settings):
        called["run_dir"] = Path(run_dir)
        called["settings"] = settings
        return approved

    monkeypatch.setattr(server, "approve_run", fake_approve_run)

    response = client.post("/api/runs/run123/approve")

    assert response.status_code == 200
    assert called["run_dir"] == tmp_path / "runs" / "run123"
    assert response.json() == {
        "run_id": "run123",
        "stage": "published",
        "published_branch": "bsp-agent/run123",
        "changed_files": ["board-camera.dts"],
    }


def test_api_approve_conflict_on_workflow_error(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    write_state(tmp_path)

    def fake_approve_run(run_dir, settings):
        raise RuntimeError("not waiting for approval")

    monkeypatch.setattr(server, "approve_run", fake_approve_run)

    response = client.post("/api/runs/run123/approve")

    assert response.status_code == 409
    assert response.json()["detail"] == "not waiting for approval"


def test_api_reject_requires_feedback(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    write_state(tmp_path)

    response = client.post("/api/runs/run123/reject", json={"feedback": ""})

    assert response.status_code == 400


def test_api_reject_calls_workflow_and_returns_state(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    rejected = write_state(tmp_path)
    rejected.new_attempt()
    called = {}

    def fake_reject_run(run_dir, feedback, settings):
        called["run_dir"] = Path(run_dir)
        called["feedback"] = feedback
        called["settings"] = settings
        return rejected

    monkeypatch.setattr(server, "reject_run", fake_reject_run)

    response = client.post("/api/runs/run123/reject", json={"feedback": "wrong regulator"})

    assert response.status_code == 200
    assert called["run_dir"] == tmp_path / "runs" / "run123"
    assert called["feedback"] == "wrong regulator"
    assert response.json() == {
        "run_id": "run123",
        "stage": "human_review",
        "attempt_no": 2,
    }


def test_api_publish_calls_workflow_and_returns_state(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    published = write_state(tmp_path, stage="published")
    published.current_attempt.published_branch = "bsp-agent/run123"
    published.current_attempt.publish_error = None
    called = {}

    def fake_publish_run(run_dir, settings):
        called["run_dir"] = Path(run_dir)
        called["settings"] = settings
        return published

    monkeypatch.setattr(server, "publish_run", fake_publish_run)

    response = client.post("/api/runs/run123/publish")

    assert response.status_code == 200
    assert called["run_dir"] == tmp_path / "runs" / "run123"
    assert response.json() == {
        "run_id": "run123",
        "stage": "published",
        "published_branch": "bsp-agent/run123",
        "publish_error": None,
    }


def test_api_publish_conflict_on_workflow_error(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    write_state(tmp_path)

    def fake_publish_run(run_dir, settings):
        raise RuntimeError("not waiting for publish retry")

    monkeypatch.setattr(server, "publish_run", fake_publish_run)

    response = client.post("/api/runs/run123/publish")

    assert response.status_code == 409
    assert response.json()["detail"] == "not waiting for publish retry"


def test_api_abandon_calls_workflow_and_returns_state(tmp_path: Path, monkeypatch) -> None:
    import agent.server as server

    client = make_client(tmp_path, monkeypatch)
    abandoned = write_state(tmp_path, stage="report")
    called = {}

    def fake_abandon_run(run_dir, settings):
        called["run_dir"] = Path(run_dir)
        called["settings"] = settings
        return abandoned

    monkeypatch.setattr(server, "abandon_run", fake_abandon_run)

    response = client.post("/api/runs/run123/abandon")

    assert response.status_code == 200
    assert called["run_dir"] == tmp_path / "runs" / "run123"
    assert response.json() == {
        "run_id": "run123",
        "stage": "report",
    }


def test_api_rejects_invalid_run_ids(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    assert client.get("/api/runs/%2E%2E").status_code == 400
    assert client.get("/api/runs/bad/id").status_code == 400
