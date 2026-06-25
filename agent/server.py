from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response

from agent.config import get_settings
from agent.nodes.workflow import create_run
from agent import run_lock
from agent.webhook import build_issue_text, build_notes_url, extract_log_block, verify_token


logger = logging.getLogger(__name__)
app = FastAPI(title="Jetson BSP Agent Webhook Server")
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
            if state.stage == "report":
                run_lock.release_active(settings.runs_dir)
        except Exception:
            run_lock.release_active(settings.runs_dir)
            logger.exception("GitLab webhook repair run failed")
