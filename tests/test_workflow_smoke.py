import json
import subprocess
from pathlib import Path

from agent.config import Settings
from agent import run_lock
from agent.graph import apply_patch_node, human_review_node, validate_patch_node, write_no_patch_node
from agent.nodes.workflow import (
    abandon_run,
    approve_run,
    create_run,
    list_pending_runs,
    publish_run,
    reject_run,
)
from agent.nodes.workflow import _keywords_for_attempt
from agent.state import BSPAgentState, RepairAttempt
from agent.tools.git_tools import GitError


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
        "react_evidence_enabled": "REACT_EVIDENCE_ENABLED",
        "llm_base_url": "LLM_BASE_URL",
        "llm_api_key": "LLM_API_KEY",
        "llm_model": "LLM_MODEL",
        "gitlab_token": "GITLAB_TOKEN",
        "gitlab_webhook_token": "GITLAB_WEBHOOK_TOKEN",
        "bsp_repo_path": "BSP_REPO_PATH",
        "bsp_base_branch": "BSP_BASE_BRANCH",
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
        "REACT_EVIDENCE_ENABLED": False,
        "GIT_REMOTE": "origin",
        "GITLAB_TOKEN": "",
        "GITLAB_WEBHOOK_TOKEN": "",
        "BSP_REPO_PATH": tmp_path / "repo",
        "BSP_BASE_BRANCH": "",
    }
    values.update(normalized_overrides)
    return Settings(**values)


def make_log(tmp_path: Path) -> Path:
    log = tmp_path / "dmesg.txt"
    log.write_text("imx219 probe failed i2c -121\n", encoding="utf-8")
    return log


def current_git_branch(repo: Path) -> str:
    return subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def add_pushable_origin(repo: Path, bare: Path) -> None:
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(
        ["git", "push", "-u", "origin", current_git_branch(repo)],
        cwd=repo,
        check=True,
        capture_output=True,
    )


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


PATCH_OKAY = """FILE: board.dts
<<<<<<< SEARCH
status = "disabled";
=======
status = "okay";
>>>>>>> REPLACE
"""

PATCH_OKAY_SPECIFIC = """FILE: board.dts
<<<<<<< SEARCH
status = "disabled";
=======
status = "okay-specific";
>>>>>>> REPLACE
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


def test_list_pending_runs_only_returns_human_review_runs(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path)
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo,
        issue="camera probe failed\nextra details",
        logs=[make_log(tmp_path)],
        settings=settings,
        issue_notes_url="https://gitlab.example/api/v4/projects/42/issues/7/notes",
    )

    rows = list_pending_runs(settings)

    assert len(rows) == 1
    assert rows[0]["run_id"] == state.run_id
    assert rows[0]["issue_no"] == "7"
    assert rows[0]["changed_files"] == ["board.dts"]
    assert rows[0]["code_review"] == "pass"
    assert rows[0]["issue_first_line"] == "camera probe failed"

    state.stage = "target_ready"
    state.save()

    assert list_pending_runs(settings) == []


def test_approve_with_auto_push_publishes_branch(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    bare = tmp_path / "origin.git"
    add_pushable_origin(repo, bare)
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


def test_publish_run_retry_posts_note_and_releases_lock(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, GITLAB_TOKEN="token")
    run_dir = tmp_path / "runs" / "run123"
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        stage="publish_failed",
        issue="camera failed",
        issue_notes_url="https://gitlab.example/api/v4/projects/42/issues/7/notes",
        attempts=[
            RepairAttempt(
                attempt_no=1,
                patch_status="applied",
                changed_files=["board.dts"],
                publish_status="failed",
                publish_error="push failed",
            )
        ],
    )
    state.save()
    assert run_lock.acquire_active(settings.runs_dir)
    posted = {}

    def fake_do_publish(loaded, publish_settings):
        loaded.stage = "published"
        loaded.current_attempt.publish_status = "pushed"
        loaded.current_attempt.published_branch = "bsp-agent/run123"
        loaded.current_attempt.publish_error = None
        loaded.save()
        return loaded

    def fake_post_issue_note(notes_url, token, body):
        posted["notes_url"] = notes_url
        posted["token"] = token
        posted["body"] = body
        return True

    monkeypatch.setattr("agent.graph._do_publish", fake_do_publish)
    monkeypatch.setattr("agent.tools.gitlab_tools.post_issue_note", fake_post_issue_note)

    result = publish_run(run_dir, settings)

    assert result.stage == "published"
    assert not run_lock.is_active(settings.runs_dir)
    assert posted["notes_url"] == state.issue_notes_url
    assert posted["token"] == "token"
    assert "bsp-agent/run123" in posted["body"]


def test_publish_run_requires_publish_failed_stage(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    run_dir = tmp_path / "runs" / "run123"
    BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        stage="human_review",
        issue="camera failed",
    ).save()

    try:
        publish_run(run_dir, settings)
    except RuntimeError as exc:
        assert "not waiting for publish retry" in str(exc)
    else:
        raise AssertionError("publish_run should reject non-publish_failed stage")


def test_abandon_run_sets_report_and_releases_lock(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    run_dir = tmp_path / "runs" / "run123"
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        stage="publish_failed",
        issue="camera failed",
        attempts=[RepairAttempt(attempt_no=1, patch_status="applied")],
    )
    state.save()
    assert run_lock.acquire_active(settings.runs_dir)
    commands = []

    def fake_run_git(repo_path, args):
        commands.append(args)

    monkeypatch.setattr("agent.nodes.workflow.run_git", fake_run_git)
    monkeypatch.setattr("agent.nodes.workflow._cleanup_managed_branch", lambda state, settings: None)

    result = abandon_run(run_dir, settings)

    assert result.stage == "report"
    assert commands == [["reset", "--hard"], ["clean", "-fd"]]
    assert not run_lock.is_active(settings.runs_dir)


def test_managed_run_creates_work_branch_at_start(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    bare = tmp_path / "origin.git"
    add_pushable_origin(repo, bare)
    settings = make_settings(tmp_path, AUTO_PUSH_ENABLED=True, GIT_REMOTE="origin")
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    assert state.stage == "human_review"
    assert current_git_branch(repo) == f"bsp-agent/{state.run_id}"


def test_managed_pull_failure_aborts_run(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, AUTO_PUSH_ENABLED=True, GIT_REMOTE="origin")

    try:
        create_run(repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings)
    except GitError:
        pass
    else:
        raise AssertionError("create_run should abort when managed pull fails")

    assert not settings.runs_dir.exists()


def test_managed_no_patch_deletes_empty_work_branch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base_branch = current_git_branch(repo)
    bare = tmp_path / "origin.git"
    add_pushable_origin(repo, bare)
    settings = make_settings(tmp_path, AUTO_PUSH_ENABLED=True, GIT_REMOTE="origin")

    state = create_run(
        repo=repo, issue="camera probe failed", logs=[make_log(tmp_path)], settings=settings
    )

    assert state.stage == "report"
    assert current_git_branch(repo) == base_branch
    branches = subprocess.run(
        ["git", "branch", "--list", f"bsp-agent/{state.run_id}"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert branches.strip() == ""


def test_published_webhook_run_posts_gitlab_note(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    bare = tmp_path / "origin.git"
    add_pushable_origin(repo, bare)
    settings = make_settings(
        tmp_path,
        AUTO_PUSH_ENABLED=True,
        GIT_REMOTE="origin",
        GITLAB_TOKEN="token",
    )
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)
    notes: list[tuple[str | None, str, str]] = []

    def fake_note(notes_url: str | None, token: str, body: str) -> bool:
        notes.append((notes_url, token, body))
        return True

    monkeypatch.setattr("agent.tools.gitlab_tools.post_issue_note", fake_note)
    assert run_lock.acquire_active(settings.runs_dir)

    state = create_run(
        repo=repo,
        issue="camera probe failed",
        logs=[make_log(tmp_path)],
        settings=settings,
        issue_notes_url="https://gitlab.example/api/v4/projects/42/issues/7/notes",
    )
    assert notes == []

    state = approve_run(state.run_dir, settings)

    assert state.stage == "published"
    assert len(notes) == 1
    assert notes[0][0] == "https://gitlab.example/api/v4/projects/42/issues/7/notes"
    assert notes[0][1] == "token"
    assert f"`{state.run_id}`" in notes[0][2]
    assert f"`bsp-agent/{state.run_id}`" in notes[0][2]
    assert not run_lock.is_active(settings.runs_dir)


def test_target_ready_webhook_run_does_not_post_gitlab_note(
    tmp_path: Path, monkeypatch
) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, GITLAB_TOKEN="token")
    fake = dispatch_fake([PATCH_OKAY], [REVIEW_PASS])
    patch_llm(monkeypatch, fake)
    notes: list[str] = []
    monkeypatch.setattr(
        "agent.tools.gitlab_tools.post_issue_note",
        lambda *args, **kwargs: notes.append("called") or True,
    )

    state = create_run(
        repo=repo,
        issue="camera probe failed",
        logs=[make_log(tmp_path)],
        settings=settings,
        issue_notes_url="https://gitlab.example/api/v4/projects/42/issues/7/notes",
    )
    state = approve_run(state.run_dir, settings)

    assert state.stage == "target_ready"
    assert notes == []


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


def test_human_reject_at_budget_creates_new_attempt(tmp_path: Path, monkeypatch) -> None:
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="human_review",
        issue="camera failed",
        max_loops=1,
    )
    attempt = state.new_attempt()
    attempt.patch_status = "generated"
    state.save()
    monkeypatch.setattr(
        "agent.graph.interrupt",
        lambda payload: {"action": "reject", "feedback": "use the board-specific DTS"},
    )

    result = human_review_node({"state": state})

    assert result["review_route"] == "classify_error"
    assert state.human_directed is True
    assert state.stage == "classify_error"
    assert len(state.attempts) == 2
    assert state.attempts[0].human_review_status == "rejected"
    assert state.attempts[0].human_feedback == "use the board-specific DTS"


def test_write_no_patch_human_directed_budget_routes_human_review(tmp_path: Path) -> None:
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="propose_patch",
        issue="camera failed",
        max_loops=1,
        human_directed=True,
    )
    state.new_attempt()
    state.save()

    result = write_no_patch_node({"state": state, "no_patch_reason": "no safe patch"})

    assert result["no_patch_route"] == "human_review"
    assert state.stage == "human_review"
    assert state.current_attempt.patch_status == "no_patch"


def test_write_no_patch_pre_human_budget_still_ends_report(tmp_path: Path) -> None:
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="propose_patch",
        issue="camera failed",
        max_loops=1,
    )
    state.new_attempt()
    state.save()

    result = write_no_patch_node({"state": state, "no_patch_reason": "no safe patch"})

    assert result["no_patch_route"] == "end"
    assert state.stage == "report"
    assert state.current_attempt.patch_status == "no_patch"


def test_validate_patch_edit_error_routes_write_no_patch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="validate_patch",
        issue="camera failed",
    )
    state.new_attempt()
    state.save()
    edit_text = """FILE: board.dts
<<<<<<< SEARCH
missing
=======
new
>>>>>>> REPLACE
"""

    result = validate_patch_node({"state": state, "diff_text": edit_text})

    assert result["validate_route"] == "write_no_patch"
    assert "SEARCH not found" in result["no_patch_reason"]
    assert state.current_attempt.patch_status == "failed"


def test_validate_patch_persists_edits_and_preview_diff(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="validate_patch",
        issue="camera failed",
    )
    state.new_attempt()
    state.save()

    result = validate_patch_node({"state": state, "diff_text": PATCH_OKAY})

    assert result["validate_route"] == "code_review_agent"
    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    assert (attempt_dir / "edits.md").read_text(encoding="utf-8") == PATCH_OKAY
    patch_md = (attempt_dir / "patch.md").read_text(encoding="utf-8")
    assert "--- a/board.dts" in patch_md
    assert '+status = "okay";' in patch_md
    assert state.current_attempt.changed_files == ["board.dts"]
    assert state.current_attempt.patch_status == "generated"


def test_apply_patch_node_applies_edits_md(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="apply_patch",
        issue="camera failed",
    )
    attempt = state.new_attempt()
    attempt.patch_status = "generated"
    state.save()
    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "edits.md").write_text(PATCH_OKAY, encoding="utf-8")

    result = apply_patch_node({"state": state})

    assert result["state"].stage == "target_ready"
    assert state.current_attempt.patch_status == "applied"
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'


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
