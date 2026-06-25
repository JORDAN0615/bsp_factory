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


def current_branch(repo_path: str | Path) -> str:
    return run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def checkout_branch(repo_path: str | Path, name: str, create: bool = False) -> None:
    if not name.strip() or any(char.isspace() for char in name):
        raise GitError("branch name must be non-empty and whitespace-free")
    args = ["checkout", "-b", name] if create else ["checkout", name]
    run_git(repo_path, args)


def commit_all(repo_path: str | Path, message: str) -> str:
    if not message.strip():
        raise GitError("commit message must be non-empty")
    if not get_git_status(repo_path).strip():
        raise GitError("nothing to commit")
    run_git(repo_path, ["add", "-A"])
    run_git(repo_path, ["commit", "-m", message])
    return run_git(repo_path, ["rev-parse", "HEAD"]).stdout.strip()


def push_branch(
    repo_path: str | Path,
    remote: str,
    branch: str,
    set_upstream: bool = True,
) -> None:
    if not remote.strip() or any(char.isspace() for char in remote):
        raise GitError("remote must be non-empty and whitespace-free")
    if not branch.strip() or any(char.isspace() for char in branch):
        raise GitError("branch must be non-empty and whitespace-free")
    if branch in {"main", "master"}:
        raise GitError(f"refusing to push protected branch {branch}")
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.extend([remote, branch])
    run_git(repo_path, args)


def pull_ff_only(repo_path: str | Path, remote: str, branch: str) -> None:
    if not remote.strip() or any(char.isspace() for char in remote):
        raise GitError("remote must be non-empty and whitespace-free")
    args = ["pull", "--ff-only", remote]
    if branch:
        if any(char.isspace() for char in branch):
            raise GitError("branch must be whitespace-free")
        args.append(branch)
    run_git(repo_path, args)


def branch_exists(repo_path: str | Path, name: str) -> bool:
    if not name.strip() or any(char.isspace() for char in name):
        raise GitError("branch name must be non-empty and whitespace-free")
    result = run_git(
        repo_path,
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
        check=False,
    )
    return result.returncode == 0


def delete_branch(repo_path: str | Path, name: str) -> None:
    if not name.strip() or any(char.isspace() for char in name):
        raise GitError("branch name must be non-empty and whitespace-free")
    run_git(repo_path, ["branch", "-D", name])
