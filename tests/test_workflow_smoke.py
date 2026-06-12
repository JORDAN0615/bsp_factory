import subprocess
from pathlib import Path

from agent.config import Settings
from agent.nodes.workflow import approve_run, create_run, reject_run
from agent.nodes.workflow import _keywords_for_attempt
from agent.state import BSPAgentState


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_create_run_smoke_no_patch_when_llm_unavailable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "add", "board.dts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    log = tmp_path / "dmesg.txt"
    log.write_text("imx219 probe failed i2c -121\n", encoding="utf-8")

    settings = Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
    )

    state = create_run(repo=repo, issue="camera probe failed", logs=[log], settings=settings)

    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    assert state.stage == "human_review"
    assert (attempt_dir / "selected_skills.json").exists()
    assert (attempt_dir / "retrieved_skills.md").exists()
    assert (attempt_dir / "repo_inspection.md").exists()
    assert (attempt_dir / "proposed_patch_prompt.md").exists()
    assert (attempt_dir / "no_patch.md").exists()
    assert (Path(state.run_dir) / "checkpoints.sqlite").exists()
    # The MVP artifact layout has no standalone memory files.
    assert not (attempt_dir / "run_memory.md").exists()
    assert not (attempt_dir / "attempt_memory.json").exists()
    assert not (attempt_dir / "attempt_memory.md").exists()


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


def test_approve_resumes_human_review_interrupt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "add", "board.dts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    log = tmp_path / "dmesg.txt"
    log.write_text("imx219 probe failed i2c -121\n", encoding="utf-8")
    settings = Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
    )

    def fake_chat_completion(*args, **kwargs) -> str:
        messages = args[1] if len(args) > 1 else kwargs["messages"]
        if "select Jetson BSP skills" in messages[0]["content"]:
            return (
                '{"selected_skills": ["jetson-customize-camera"], '
                '"confidence": 0.9, "reason": "camera issue"}'
            )
        return """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay";
"""

    monkeypatch.setattr("agent.nodes.workflow.chat_completion", fake_chat_completion)
    state = create_run(repo=repo, issue="camera probe failed", logs=[log], settings=settings)

    assert state.stage == "human_review"
    assert state.current_attempt.patch_status == "applied"

    state = approve_run(state.run_dir, settings)

    assert state.stage == "target_ready"
    assert state.current_attempt.human_review_status == "approved"
    assert (Path(state.run_dir) / "attempts" / "001" / "review.md").read_text() == "Status: approved\n"
    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    # patch.md is the canonical patch artifact.
    patch_md = (attempt_dir / "patch.md").read_text(encoding="utf-8")
    assert "Attempt: `001`" in patch_md
    assert "- `board.dts`" in patch_md
    assert '```diff' in patch_md
    assert '+status = "okay";' in patch_md
    assert not (attempt_dir / "patch.diff").exists()
    assert not (attempt_dir / "patch_summary.md").exists()
    assert not (attempt_dir / "changed_files.json").exists()


def test_reject_resumes_and_rolls_back_attempt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "add", "board.dts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    log = tmp_path / "dmesg.txt"
    log.write_text("imx219 probe failed i2c -121\n", encoding="utf-8")
    settings = Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
    )
    calls = {"count": 0}
    prompts: list[str] = []

    def fake_chat_completion(*args, **kwargs) -> str:
        messages = args[1] if len(args) > 1 else kwargs["messages"]
        if "select Jetson BSP skills" in messages[0]["content"]:
            return (
                '{"selected_skills": ["jetson-customize-camera"], '
                '"confidence": 0.9, "reason": "camera issue"}'
            )
        calls["count"] += 1
        prompts.append(messages[-1]["content"])
        if calls["count"] == 1:
            return """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay";
"""
        assert "try board-specific file only" in prompts[-1]
        assert "Retry context (previous attempts in this run):" in prompts[-1]
        assert "## Attempt 001" in prompts[-1]
        return """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay-specific";
"""

    monkeypatch.setattr("agent.nodes.workflow.chat_completion", fake_chat_completion)
    state = create_run(repo=repo, issue="camera probe failed", logs=[log], settings=settings)

    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'

    state = reject_run(state.run_dir, "try board-specific file only", settings)

    assert state.stage == "human_review"
    assert len(state.attempts) == 2
    assert state.attempts[0].human_review_status == "rejected"
    assert state.current_attempt.patch_status == "applied"
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "okay-specific";\n'

    # The retry context is built at runtime; no memory files are created.
    assert not (Path(state.run_dir) / "attempts" / "002" / "run_memory.md").exists()
    assert not (Path(state.run_dir) / "attempts" / "001" / "attempt_memory.json").exists()
    # The actual patch prompt is recorded for both attempts.
    second_prompt = (
        Path(state.run_dir) / "attempts" / "002" / "proposed_patch_prompt.md"
    ).read_text(encoding="utf-8")
    assert "## Attempt 001" in second_prompt
    assert "try board-specific file only" in second_prompt
