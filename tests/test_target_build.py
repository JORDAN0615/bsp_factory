import subprocess
from pathlib import Path

from agent.config import Settings
from agent.graph import route_after_code_review, route_after_target_build
from agent.tools.bsp_build import run_bsp_build


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "LLM_API_KEY": "EMPTY",
        "LLM_MODEL": "test",
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
    }
    values.update(overrides)
    return Settings(**values)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _entrypoint(tmp_path: Path, exit_code: int) -> Path:
    script = tmp_path / "build_stub.sh"
    script.write_text(
        f'#!/usr/bin/env bash\necho "building $1 scope=$2"\nexit {exit_code}\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_run_bsp_build_success(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, BUILD_ENTRYPOINT=str(_entrypoint(tmp_path, 0)))

    result = run_bsp_build(repo, "", "full", settings, log_path=tmp_path / "build.log")

    assert result.ok is True and result.ran is True and result.returncode == 0
    assert "building" in (tmp_path / "build.log").read_text(encoding="utf-8")
    # Staging worktree cleaned up; real tree untouched.
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'


def test_run_bsp_build_failure_captures_log(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, BUILD_ENTRYPOINT=str(_entrypoint(tmp_path, 2)))

    result = run_bsp_build(repo, "", "full", settings, log_path=tmp_path / "build.log")

    assert result.ok is False and result.ran is True and result.returncode == 2


def test_run_bsp_build_missing_entrypoint_did_not_run(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, BUILD_ENTRYPOINT=str(tmp_path / "nope.sh"))

    result = run_bsp_build(repo, "", "full", settings, log_path=tmp_path / "build.log")

    assert result.ok is False and result.ran is False and result.returncode == 127


def test_route_after_code_review_gates_on_target_build(tmp_path: Path) -> None:
    on = make_settings(tmp_path, TARGET_BUILD_ENABLED=True)
    off = make_settings(tmp_path, TARGET_BUILD_ENABLED=False)

    passed = {"review_agent_route": "human_review"}
    rejected = {"review_agent_route": "classify_error"}

    assert route_after_code_review({**passed, "settings": on}) == "target_build"
    assert route_after_code_review({**passed, "settings": off}) == "human_review"
    # A rejected review still loops back regardless of the build gate.
    assert route_after_code_review({**rejected, "settings": on}) == "classify_error"


def test_route_after_target_build() -> None:
    assert route_after_target_build({"build_route": "human_review"}) == "human_review"
    assert route_after_target_build({"build_route": "classify_error"}) == "classify_error"
    assert route_after_target_build({}) == "human_review"
