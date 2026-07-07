from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from agent.config import get_settings
from agent.nodes.workflow import (
    abandon_run,
    approve_run,
    create_run,
    delete_run,
    list_pending_runs,
    publish_run,
    reject_run,
    retry_run,
)
from agent import run_lock
from agent.state import BSPAgentState
from agent.tools.artifact_tools import attempt_dir
from agent.webhook import build_issue_text, build_notes_url, extract_log_block, verify_token


logger = logging.getLogger(__name__)
app = FastAPI(title="Jetson BSP Agent Webhook Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings = get_settings()
_RUN_LOCK = threading.Lock()


def _already_processed(delivery_id: str) -> bool:
    if not delivery_id:
        return False
    webhook_dir = settings.runs_dir / ".webhook"
    webhook_dir.mkdir(parents=True, exist_ok=True)
    marker = webhook_dir / delivery_id
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return True
    return False


def _run_dir(run_id: str) -> Path:
    if not run_id or "/" in run_id or "\\" in run_id or "." in run_id:
        raise HTTPException(status_code=400, detail="invalid run_id")
    runs_dir = settings.runs_dir.resolve()
    run_dir = (settings.runs_dir / run_id).resolve()
    if not run_dir.is_relative_to(runs_dir):
        raise HTTPException(status_code=400, detail="invalid run_id")
    if not run_dir.is_dir() or not (run_dir / "state.json").is_file():
        raise HTTPException(status_code=404, detail="run not found")
    return run_dir


def _read_artifact(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runs")
def api_runs() -> list[dict]:
    return list_pending_runs(settings)


@app.get("/api/runs/{run_id:path}")
def api_run_detail(run_id: str) -> dict:
    state = BSPAgentState.load(_run_dir(run_id))
    attempt = state.current_attempt
    artifact_dir = attempt_dir(state.run_dir, attempt.attempt_no)
    return {
        "run_id": state.run_id,
        "stage": state.stage,
        "issue": state.issue,
        "attempt_no": attempt.attempt_no,
        "changed_files": attempt.changed_files,
        "publish_error": attempt.publish_error,
        "mode": "llm_failure" if state.failure_reason else "patch_review",
        "failure_reason": state.failure_reason,
        "code_review": _read_artifact(artifact_dir / "code_review.md"),
        "diff": _read_artifact(artifact_dir / "patch.md"),
        "repo_inspection": _read_artifact(artifact_dir / "repo_inspection.md"),
    }


@app.post("/api/runs/{run_id:path}/approve")
def api_approve_run(run_id: str) -> dict:
    try:
        state = approve_run(_run_dir(run_id), settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    attempt = state.current_attempt
    return {
        "run_id": state.run_id,
        "stage": state.stage,
        "published_branch": attempt.published_branch,
        "changed_files": attempt.changed_files,
    }


@app.post("/api/runs/{run_id:path}/reject")
def api_reject_run(run_id: str, payload: dict[str, str]) -> dict:
    feedback = (payload.get("feedback") or "").strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="feedback is required")
    try:
        state = reject_run(_run_dir(run_id), feedback, settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": state.run_id,
        "stage": state.stage,
        "attempt_no": state.current_attempt.attempt_no,
    }


@app.post("/api/runs/{run_id:path}/publish")
def api_publish_run(run_id: str) -> dict:
    try:
        state = publish_run(_run_dir(run_id), settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    attempt = state.current_attempt
    return {
        "run_id": state.run_id,
        "stage": state.stage,
        "published_branch": attempt.published_branch,
        "publish_error": attempt.publish_error,
    }


@app.post("/api/runs/{run_id:path}/retry")
def api_retry_run(run_id: str) -> dict:
    try:
        state = retry_run(_run_dir(run_id), settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": state.run_id,
        "stage": state.stage,
        "attempt_no": state.current_attempt.attempt_no,
        "failure_reason": state.failure_reason,
    }


@app.post("/api/runs/{run_id:path}/abandon")
def api_abandon_run(run_id: str) -> dict:
    try:
        state = abandon_run(_run_dir(run_id), settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": state.run_id,
        "stage": state.stage,
    }


@app.delete("/api/runs/{run_id:path}")
def api_delete_run(run_id: str) -> dict:
    try:
        deleted_id = delete_run(_run_dir(run_id), settings)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": deleted_id, "deleted": True}


@app.post("/webhook/github")
async def github_webhook(request: Request, background: BackgroundTasks) -> Response:
    raw = await request.body()
    header_token = request.headers.get("X-Gitlab-Token", "")
    if not verify_token(settings.gitlab_webhook_token, header_token):
        raise HTTPException(status_code=401, detail="invalid token")
    if request.headers.get("X-Gitlab-Event") != "Issue Hook":
        return Response(status_code=204)
    payload = json.loads(raw)
    if payload.get("object_kind") != "issue":
        return Response(status_code=204)
    object_attributes = payload.get("object_attributes", {})
    if object_attributes.get("action") != "open":
        return Response(status_code=204)
    delivery = request.headers.get("X-Gitlab-Event-UUID", "")
    if _already_processed(delivery):
        return Response(status_code=200)
    if not run_lock.acquire_active(settings.runs_dir):
        logger.info("a run is already in progress; rejecting delivery %s", delivery)
        return Response(status_code=409)
    description = object_attributes.get("description")
    issue_text = build_issue_text(object_attributes.get("title"), description)
    log_text = extract_log_block(description)
    project_id = payload.get("project", {}).get("id")
    notes_url = build_notes_url(settings.gitlab_api_url, project_id, object_attributes.get("iid"))
    background.add_task(run_issue, issue_text, log_text, notes_url)
    return Response(status_code=202)


def run_issue(issue_text: str, log_text: str | None, notes_url: str | None) -> None:
    with _RUN_LOCK:
        logs: list[Path] = []
        if log_text:
            webhook_dir = settings.runs_dir / ".webhook"
            webhook_dir.mkdir(parents=True, exist_ok=True)
            log_path = webhook_dir / f"issue-log-{time.time_ns()}.txt"
            log_path.write_text(log_text, encoding="utf-8")
            logs.append(log_path)
        try:
            state = create_run(
                repo=settings.bsp_repo_path,
                issue=issue_text,
                logs=logs,
                settings=settings,
                issue_notes_url=notes_url,
            )
            if state.stage != "human_review":
                run_lock.release_active(settings.runs_dir)
        except Exception:
            run_lock.release_active(settings.runs_dir)
            logger.exception("GitLab webhook repair run failed")
