from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


Stage = Literal[
    "intake",
    "classify_error",
    "select_skills",
    "load_skill",
    "inspect_repo",
    "propose_patch",
    "validate_patch",
    "code_review",
    "apply_patch",
    "publish",
    "published",
    "publish_failed",
    "human_review",
    "target_ready",
    "run_tests",
    "analyze_test",
    "report",
    "done",
    "failed",
]


PatchStatus = Literal["not_generated", "generated", "applied", "no_patch", "failed"]
ReviewStatus = Literal["pending", "approved", "rejected"]
CodeReviewDecision = Literal["pass", "reject", "needs_human"]
ValidationStatus = Literal["pending", "running", "success", "failed"]
PublishStatus = Literal["pending", "pushed", "failed"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TargetInfo(BaseModel):
    ssh_target: str
    git_ref: str
    host: str | None = None
    user: str | None = None
    port: int = 22
    build_label: str | None = None
    registered_at: str = Field(default_factory=now_iso)


class ValidationRunInfo(BaseModel):
    validation_id: str
    script: str
    target_ssh: str
    status: ValidationStatus = "pending"
    returncode: int | None = None
    duration_sec: float | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class RepairAttempt(BaseModel):
    attempt_no: int
    patch_status: PatchStatus = "not_generated"
    human_review_status: ReviewStatus = "pending"
    human_feedback: str | None = None
    code_review_decision: CodeReviewDecision | None = None
    code_review_confidence: float | None = None
    code_review_findings: list[str] = Field(default_factory=list)
    code_review_required_changes: list[str] = Field(default_factory=list)
    publish_status: PublishStatus | None = None
    published_branch: str | None = None
    published_commit: str | None = None
    publish_error: str | None = None
    selected_skills: list[str] = Field(default_factory=list)
    bug_type: str | None = None
    suspected_areas: list[str] = Field(default_factory=list)
    error_signatures: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    target: TargetInfo | None = None
    validation_runs: list[ValidationRunInfo] = Field(default_factory=list)
    analysis_result: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class BSPAgentState(BaseModel):
    run_id: str
    repo_path: str
    run_dir: str
    stage: Stage = "intake"
    issue: str
    input_logs: list[str] = Field(default_factory=list)
    attempts: list[RepairAttempt] = Field(default_factory=list)
    max_loops: int = 3
    managed_base_branch: str | None = None
    issue_notes_url: str | None = None
    report_path: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @property
    def current_attempt(self) -> RepairAttempt:
        if not self.attempts:
            self.attempts.append(RepairAttempt(attempt_no=1))
        return self.attempts[-1]

    def new_attempt(self) -> RepairAttempt:
        attempt = RepairAttempt(attempt_no=len(self.attempts) + 1)
        self.attempts.append(attempt)
        self.touch()
        return attempt

    def touch(self) -> None:
        self.updated_at = now_iso()
        if self.attempts:
            self.attempts[-1].updated_at = self.updated_at

    @classmethod
    def load(cls, run_dir: str | Path) -> "BSPAgentState":
        path = Path(run_dir) / "state.json"
        return cls.model_validate_json(path.read_text())

    def save(self) -> None:
        Path(self.run_dir).mkdir(parents=True, exist_ok=True)
        Path(self.run_dir, "state.json").write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )

    def to_report_context(self) -> dict[str, Any]:
        return self.model_dump()
