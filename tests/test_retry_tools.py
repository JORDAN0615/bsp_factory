from pathlib import Path

from agent.state import BSPAgentState, ValidationRunInfo
from agent.tools.artifact_tools import write_text
from agent.tools.retry_tools import build_retry_context


def make_state(tmp_path: Path) -> BSPAgentState:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    return BSPAgentState(
        run_id="run-1",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        issue="camera probe failed",
    )


def write_patch_md(attempt_path: Path) -> None:
    write_text(
        attempt_path / "patch.md",
        "# Patch\n\n"
        "Attempt: `001`\n\n"
        "## Changed Files\n\n"
        "- `board.dts`\n\n"
        "## Diff\n\n"
        "```diff\n"
        "--- a/board.dts\n"
        "+++ b/board.dts\n"
        "@@ -1 +1 @@\n"
        '-status = "disabled";\n'
        '+status = "okay";\n'
        "```\n",
    )


def test_retry_context_first_attempt_has_no_previous(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    state.new_attempt()

    text = build_retry_context(state)

    assert "(No previous attempts in this run.)" in text


def test_retry_context_excludes_current_attempt(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    first = state.new_attempt()
    first.bug_type = "camera"
    first.selected_skills = ["jetson-customize-camera"]
    first.patch_status = "applied"
    first.changed_files = ["board.dts"]
    first.human_review_status = "rejected"
    first.human_feedback = "wrong file"
    attempt_path = Path(state.run_dir) / "attempts" / "001"
    write_patch_md(attempt_path)
    stderr = tmp_path / "stderr.txt"
    stderr.write_text("imx219 probe failed -121\n", encoding="utf-8")
    first.validation_runs.append(
        ValidationRunInfo(
            validation_id="001_boot_check",
            script="boot_check.sh",
            target_ssh="nvidia@host",
            status="failed",
            returncode=1,
            stderr_path=str(stderr),
        )
    )
    state.new_attempt()

    text = build_retry_context(state)

    assert "## Attempt 001" in text
    # Selected skills, reject feedback, changed files, patch content, and
    # validation exit/stderr summary all appear in the retry context.
    assert "jetson-customize-camera" in text
    assert "wrong file" in text
    assert "`board.dts`" in text
    assert '+status = "okay";' in text
    assert "exit `1`" in text
    assert "imx219 probe failed -121" in text
    # The current in-progress attempt never appears in its own retry context.
    assert "## Attempt 002" not in text


def test_retry_context_extracts_no_patch_reason(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    first = state.new_attempt()
    first.patch_status = "no_patch"
    write_text(
        Path(state.run_dir) / "attempts" / "001" / "no_patch.md",
        "# No Patch\n\n## Reason\n\nOld block not found in board.dts.\n\n"
        "## Requested Information\n\n- More logs.\n",
    )
    state.new_attempt()

    text = build_retry_context(state)

    assert "No-patch / failure reason: Old block not found in board.dts." in text


def test_retry_context_summarizes_validation_tails(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    first = state.new_attempt()
    stdout = tmp_path / "stdout.txt"
    stdout.write_text("\n".join(f"line {n}" for n in range(1, 31)) + "\n", encoding="utf-8")
    first.validation_runs.append(
        ValidationRunInfo(
            validation_id="001_boot_check",
            script="boot_check.sh",
            target_ssh="nvidia@host",
            status="failed",
            returncode=1,
            stdout_path=str(stdout),
        )
    )
    state.new_attempt()

    text = build_retry_context(state)

    # Only the bounded tail of stdout is included.
    assert "line 30" in text
    assert "line 21" in text
    assert "line 1\n" not in text


def test_retry_context_builds_at_runtime_without_memory_files(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    first = state.new_attempt()
    first.patch_status = "applied"
    state.new_attempt()

    build_retry_context(state)

    run_dir = Path(state.run_dir)
    leftovers = (
        list(run_dir.rglob("run_memory.md"))
        + list(run_dir.rglob("attempt_memory.json"))
        + list(run_dir.rglob("attempt_memory.md"))
    )
    assert leftovers == []
