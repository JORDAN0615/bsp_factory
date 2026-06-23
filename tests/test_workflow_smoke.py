import json
import subprocess
from pathlib import Path

from agent.config import Settings
from agent.nodes.workflow import approve_run, create_run, reject_run
from agent.nodes.workflow import _keywords_for_attempt
from agent.state import BSPAgentState


REVIEW_PASS = json.dumps(
    {
        "decision": "pass",
        "confidence": 0.95,
        "findings": [],
        "required_changes": [],
    }
)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "add", "board.dts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def make_settings(tmp_path: Path, **overrides) -> Settings:
    alias_overrides = {
        "auto_push_enabled": "AUTO_PUSH_ENABLED",
        "git_remote": "GIT_REMOTE",
        "code_review_enabled": "CODE_REVIEW_ENABLED",
        "llm_base_url": "LLM_BASE_URL",
        "llm_api_key": "LLM_API_KEY",
        "llm_model": "LLM_MODEL",
    }
    normalized_overrides = {
        alias_overrides.get(key, key): value for key, value in overrides.items()
    }
    values = {
        "LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "LLM_API_KEY": "EMPTY",
        "LLM_MODEL": "test",
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
        "AUTO_PUSH_ENABLED": False,
        "GIT_REMOTE": "origin",
    }
    values.update(normalized_overrides)
    return Settings(**values)


def make_log(tmp_path: Path) -> Path:
    log = tmp_path / "dmesg.txt"
    log.write_text("imx219 probe failed i2c -121\n", encoding="utf-8")
    return log


def patch_llm(monkeypatch, fake) -> None:
    """The skill-selection, patch-agent, and review-agent calls each import
    chat_completion into their own module namespace."""
    monkeypatch.setattr("agent.graph.chat_completion", fake)
    monkeypatch.setattr("agent.nodes.workflow.chat_completion", fake)
    monkeypatch.setattr("agent.tools.review_tools.chat_completion", fake)


def dispatch_fake(patch_responses, review_responses):
    """Build a fake chat_completion that dispatches on the system message."""
    state = {"patch": 0, "review": 0, "prompts": []}

    def fake(*args, **kwargs) -> str:
        messages = args[1] if len(args) > 1 else kwargs["messages"]
        system = messages[0]["content"]
        if "select Jetson BSP skills" in system:
            return (
                '{"selected_skills": ["jetson-customize-camera"], '
                '"confidence": 0.9, "reason": "camera issue"}'
            )
        if "code reviewer" in system:
            index = min(state["review"], len(review_responses) - 1)
            state["review"] += 1
            return review_responses[index]
        state["prompts"].append(messages[-1]["content"])
        index = min(state["patch"], len(patch_responses) - 1)
        state["patch"] += 1
        return patch_responses[index]

    fake.calls = state
    return fake


PATCH_OKAY = """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay";
"""

PATCH_OKAY_SPECIFIC = """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay-specific";
"""


def test_create_run_smoke_retries_to_report_when_llm_unavailable(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    # NO_PATCH attempts auto-retry until the budget is exhausted, then report.
    assert state.stage == "report"
    assert len(state.attempts) == settings.max_loops
    assert (Path(state.run_dir) / "report.md").exists()
    assert (Path(state.run_dir) / "checkpoints.sqlite").exists()
    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    assert (attempt_dir / "selected_skills.json").exists()
    assert (attempt_dir / "repo_inspection.md").exists()
    assert (attempt_dir / "proposed_patch_prompt.md").exists()
    assert (attempt_dir / "no_patch.md").exists()
    # Debug artifacts live under debug/.
    assert (attempt_dir / "debug" / "error_classification.json").exists()
    assert (attempt_dir / "debug" / "skill_catalog.json").exists()
    assert (attempt_dir / "debug" / "skill_selection.json").exists()
    assert (attempt_dir / "debug" / "retrieved_skills.md").exists()
    assert not (attempt_dir / "skill_catalog.json").exists()
    # No standalone memory files.
    assert not (attempt_dir / "run_memory.md").exists()
    assert not (attempt_dir / "attempt_memory.json").exists()


def test_multiline_issue_is_normalized_for_repo_keywords() -> None:
    state = BSPAgentState(
        run_id="run",
        repo_path="/tmp/repo",
        run_dir="/tmp/run",
        issue="After flashing custom Orin NX BSP, imx219 camera probe fails with\n"
        "i2c -121 and missing camera regulator",
    )
    attempt = state.new_attempt()
    attempt.error_signatures = ["probe failed", "i2c.*-121"]
    attempt.suspected_areas = ["camera", "regulator"]

    keywords = _keywords_for_attempt(state, attempt)

    assert all("\n" not in keyword for keyword in keywords)
    assert "imx219" in keywords
    assert "camera" in keywords
    assert "-121" in keywords


def test_approve_applies_patch_after_review(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path)
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    # Review agent passed, but human approval is still required.
    assert state.stage == "human_review"
    attempt = state.current_attempt
    assert attempt.patch_status == "generated"
    assert attempt.code_review_decision == "pass"
    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    assert (attempt_dir / "patch.md").exists()
    assert (attempt_dir / "code_review.md").exists()
    assert (attempt_dir / "review_agent_raw.json").exists()
    # The patch is NOT applied while waiting for review.
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'

    state = approve_run(state.run_dir, settings)

    # Approval applies the patch from canonical patch.md.
    assert state.stage == "target_ready"
    assert state.current_attempt.patch_status == "applied"
    assert state.current_attempt.human_review_status == "approved"
    assert state.current_attempt.publish_status is None
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'
    assert (attempt_dir / "review.md").read_text(encoding="utf-8") == "Status: approved\n"


def test_approve_with_auto_push_publishes_branch(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    settings = make_settings(tmp_path, AUTO_PUSH_ENABLED=True, GIT_REMOTE="origin")
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )
    state = approve_run(state.run_dir, settings)

    attempt = state.current_attempt
    expected_branch = f"bsp-agent/{state.run_id}"
    assert state.stage == "published"
    assert attempt.publish_status == "pushed"
    assert attempt.published_branch == expected_branch
    assert attempt.published_commit is not None
    assert len(attempt.published_commit) == 40
    assert (Path(state.run_dir) / "attempts" / "001" / "publish.json").exists()
    result = subprocess.run(
        ["git", "-C", str(bare), "rev-parse", expected_branch],
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == attempt.published_commit


def test_approve_with_auto_push_records_push_failure(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    # No remote configured -> commit succeeds, push fails.
    settings = make_settings(tmp_path, AUTO_PUSH_ENABLED=True, GIT_REMOTE="origin")
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )
    state = approve_run(state.run_dir, settings)

    attempt = state.current_attempt
    assert state.stage == "publish_failed"
    assert attempt.publish_status == "failed"
    # Commit step succeeded before the push failed.
    assert attempt.published_commit is not None
    assert len(attempt.published_commit) == 40
    # The real git error reason is captured, not swallowed.
    assert attempt.publish_error
    assert "origin" in attempt.publish_error
    publish_json = json.loads(
        (Path(state.run_dir) / "attempts" / "001" / "publish.json").read_text(encoding="utf-8")
    )
    assert publish_json["status"] == "failed"
    assert publish_json["error"]
    # Patch is still applied locally.
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'


def test_human_reject_creates_new_attempt_without_rollback(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path)
    fake = dispatch_fake([PATCH_OKAY, PATCH_OKAY_SPECIFIC], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )
    assert state.stage == "human_review"
    # Nothing applied yet, nothing to roll back.
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'

    state = reject_run(state.run_dir, "try board-specific file only", settings)

    assert state.stage == "human_review"
    assert len(state.attempts) == 2
    assert state.attempts[0].human_review_status == "rejected"
    assert state.current_attempt.patch_status == "generated"
    # Repo still untouched after reject (no rollback needed).
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'
    # Retry context with the human feedback reached the second patch prompt.
    second_prompt = fake.calls["prompts"][-1]
    assert "Retry context (previous attempts in this run):" in second_prompt
    assert "## Attempt 001" in second_prompt
    assert "try board-specific file only" in second_prompt

    state = approve_run(state.run_dir, settings)

    assert state.stage == "target_ready"
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "okay-specific";\n'


def test_code_review_reject_auto_retries(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path)
    review_reject = json.dumps(
        {
            "decision": "reject",
            "confidence": 0.8,
            "findings": ["status change not supported by inspection"],
            "required_changes": ["use the board-specific status value"],
        }
    )
    fake = dispatch_fake([PATCH_OKAY, PATCH_OKAY_SPECIFIC], [review_reject, REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    # First attempt rejected by the review agent, retried automatically.
    assert state.stage == "human_review"
    assert len(state.attempts) == 2
    assert state.attempts[0].code_review_decision == "reject"
    assert state.attempts[1].code_review_decision == "pass"
    # Review feedback reached the second patch prompt via retry context.
    second_prompt = fake.calls["prompts"][-1]
    assert "use the board-specific status value" in second_prompt
    # No human was involved in the retry; repo untouched.
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'


def test_code_review_reject_exhausted_escalates_to_human(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, max_loops=2)
    review_reject = json.dumps(
        {
            "decision": "reject",
            "confidence": 0.9,
            "findings": ["still not supported by evidence"],
            "required_changes": [],
        }
    )
    fake = dispatch_fake([PATCH_OKAY, PATCH_OKAY_SPECIFIC], [review_reject])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    # Budget exhausted after repeated review rejects -> escalate to human.
    assert state.stage == "human_review"
    assert len(state.attempts) == 2
    assert state.current_attempt.code_review_decision == "reject"
    assert state.current_attempt.patch_status == "generated"


def test_code_review_disabled_goes_straight_to_human(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, CODE_REVIEW_ENABLED=False)
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    assert state.stage == "human_review"
    attempt = state.current_attempt
    assert attempt.patch_status == "generated"
    assert attempt.code_review_decision is None
    assert not (Path(state.run_dir) / "attempts" / "001" / "code_review.md").exists()
