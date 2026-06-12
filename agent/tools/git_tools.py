from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo_path: str | Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo_path), *args]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip() or f"git failed: {' '.join(cmd)}")
    return result


def ensure_git_repo(repo_path: str | Path) -> None:
    result = run_git(repo_path, ["rev-parse", "--is-inside-work-tree"], check=True)
    if result.stdout.strip() != "true":
        raise GitError(f"Not a git working tree: {repo_path}")


def get_git_status(repo_path: str | Path) -> str:
    return run_git(repo_path, ["status", "--short"]).stdout


def ensure_clean_source(repo_path: str | Path) -> None:
    status = get_git_status(repo_path)
    if status.strip():
        raise GitError(f"BSP source repo must be clean before init-run:\n{status}")


def get_git_diff(repo_path: str | Path, unified: int = 3) -> str:
    return run_git(repo_path, ["diff", f"--unified={unified}"]).stdout


def get_git_diff_stat(repo_path: str | Path) -> str:
    return run_git(repo_path, ["diff", "--stat"]).stdout


def get_changed_files(repo_path: str | Path) -> list[str]:
    output = run_git(repo_path, ["diff", "--name-only"]).stdout
    return [line for line in output.splitlines() if line.strip()]


def current_head(repo_path: str | Path) -> str:
    return run_git(repo_path, ["rev-parse", "HEAD"]).stdout.strip()


def restore_files(repo_path: str | Path, files: list[str]) -> None:
    if files:
        run_git(repo_path, ["restore", "--", *files])
