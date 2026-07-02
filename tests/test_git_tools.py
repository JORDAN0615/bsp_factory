import subprocess
from pathlib import Path

import pytest

import agent.tools.git_tools as git_tools
from agent.tools.git_tools import (
    GitError,
    add_worktree,
    checkout_branch,
    commit_all,
    current_branch,
    diff_worktree,
    push_branch,
    remove_worktree,
    run_git as tool_run_git,
)


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, ["init"])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "Test"])
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    run_git(repo, ["add", "README.md"])
    run_git(repo, ["commit", "-m", "init"])
    return repo


def test_current_branch_returns_initial_branch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    expected = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    assert current_branch(repo) == expected


def test_checkout_branch_create_switches_branch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    checkout_branch(repo, "feature/test", create=True)

    assert current_branch(repo) == "feature/test"


def test_commit_all_commits_changes_and_rejects_empty_commit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    sha = commit_all(repo, "change readme")

    assert len(sha) == 40
    int(sha, 16)
    with pytest.raises(GitError, match="nothing to commit"):
        commit_all(repo, "second commit")
    with pytest.raises(GitError):
        commit_all(repo, " ")


def test_push_branch_pushes_feature_branch_to_local_bare_remote(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    run_git(repo, ["remote", "add", "origin", str(bare)])
    checkout_branch(repo, "feature/publish", create=True)
    (repo / "feature.txt").write_text("publish\n", encoding="utf-8")
    commit_all(repo, "feature publish")

    push_branch(repo, "origin", "feature/publish")

    result = subprocess.run(
        ["git", "-C", str(bare), "rev-parse", "feature/publish"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert len(result.stdout.strip()) == 40


@pytest.mark.parametrize("branch", ["main", "master"])
def test_push_branch_refuses_protected_branches(tmp_path: Path, branch: str) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(GitError, match=f"refusing to push protected branch {branch}"):
        push_branch(repo, "origin", branch)


def test_run_git_forces_c_locale(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, text, capture_output, check, env):
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(git_tools.subprocess, "run", fake_run)

    tool_run_git(tmp_path, ["status"])

    assert captured["env"]["LC_ALL"] == "C"
    assert captured["env"]["LANG"] == "C"


def test_worktree_add_diff_remove_roundtrip(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    staging = tmp_path / "staging"

    add_worktree(repo, staging)
    try:
        assert (staging / "README.md").exists()
        (staging / "README.md").write_text("changed\n", encoding="utf-8")
        diff = diff_worktree(staging)
        assert "--- a/README.md" in diff
        assert "+changed" in diff
    finally:
        remove_worktree(repo, staging)

    assert not staging.exists()
