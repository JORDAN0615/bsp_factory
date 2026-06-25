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
from agent.webhook import build_issue_text, extract_log_block, verify_signature


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
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(settings.github_webhook_secret, raw, signature):
        raise HTTPException(status_code=401, detail="invalid signature")
    if request.headers.get("X-GitHub-Event") != "issues":
        return Response(status_code=204)
    payload = json.loads(raw)
    if payload.get("action") != "opened":
        return Response(status_code=204)
    delivery = request.headers.get("X-GitHub-Delivery", "")
    if _already_processed(delivery):
        return Response(status_code=200)
    if not run_lock.acquire_active(settings.runs_dir):
        logger.info("a run is already in progress; rejecting delivery %s", delivery)
        return Response(status_code=202)
    issue = payload["issue"]
    issue_text = build_issue_text(issue.get("title"), issue.get("body"))
    log_text = extract_log_block(issue.get("body"))
    background.add_task(run_issue, issue_text, log_text, issue.get("comments_url"))
    return Response(status_code=202)


def run_issue(issue_text: str, log_text: str | None, comments_url: str | None) -> None:
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
                github_comments_url=comments_url,
            )
            if state.stage == "report":
                run_lock.release_active(settings.runs_dir)
        except Exception:
            run_lock.release_active(settings.runs_dir)
            logger.exception("GitHub webhook repair run failed")
