from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path, PurePath
import shutil
import subprocess
from collections.abc import Iterator

from langchain_core.tools import tool


_repo_root: ContextVar[Path | None] = ContextVar("readonly_repo_root", default=None)
_MAX_GREP_MATCHES = 200
_MAX_READ_LINES = 400


class ReadOnlyToolError(ValueError):
    pass


@contextmanager
def readonly_repo(repo_path: str | Path) -> Iterator[None]:
    root = Path(repo_path).resolve(strict=True)
    if not root.is_dir():
        raise ReadOnlyToolError(f"repo path is not a directory: {repo_path}")
    token = _repo_root.set(root)
    try:
        yield
    finally:
        _repo_root.reset(token)


def _current_root() -> Path:
    root = _repo_root.get()
    if root is None:
        raise ReadOnlyToolError("read-only repo root is not configured")
    return root


def _resolve_repo_path(path: str | None = None) -> Path:
    root = _current_root()
    if path in {None, "", "."}:
        return root
    candidate_text = str(path)
    if ".." in PurePath(candidate_text).parts:
        raise ReadOnlyToolError("path may not contain '..'")
    candidate = Path(candidate_text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ReadOnlyToolError(f"path escapes repo root: {path}")
    return resolved


def _cap_lines(text: str, limit: int) -> str:
    lines = text.splitlines()
    capped = lines[:limit]
    rendered = "\n".join(capped)
    if len(lines) > limit:
        rendered += f"\n... capped at {limit} lines"
    return rendered


@tool
def grep_repo(pattern: str, path: str | None = None) -> str:
    """Search the configured BSP repo read-only and return file:line:text matches."""
    try:
        if not pattern:
            raise ReadOnlyToolError("pattern is required")
        target = _resolve_repo_path(path)
        root = _current_root()
    except (ReadOnlyToolError, FileNotFoundError) as exc:
        return f"(error: {exc})"
    if shutil.which("rg"):
        command = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color=never",
            "--glob",
            "!.git",
            "--",
            pattern,
            str(target),
        ]
    else:
        command = ["grep", "-RIn", "--exclude-dir=.git", "--", pattern, str(target)]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode not in {0, 1}:
        return f"grep failed: {result.stderr.strip()}"
    if not result.stdout.strip():
        return "(no matches)"
    lines = []
    for line in result.stdout.splitlines():
        if line.startswith(str(root)):
            line = str(Path(line.split(":", 1)[0]).relative_to(root)) + ":" + line.split(":", 1)[1]
        lines.append(line[:1000])
    return _cap_lines("\n".join(lines), _MAX_GREP_MATCHES)


@tool
def read_file(path: str, start: int | None = None, end: int | None = None) -> str:
    """Read a line-numbered slice from a file in the configured BSP repo."""
    try:
        file_path = _resolve_repo_path(path)
        if not file_path.is_file():
            raise ReadOnlyToolError(f"path is not a file: {path}")
        if start is not None and start < 1:
            raise ReadOnlyToolError("start must be >= 1")
        if end is not None and end < 1:
            raise ReadOnlyToolError("end must be >= 1")
        if start is not None and end is not None and end < start:
            raise ReadOnlyToolError("end must be >= start")
    except (ReadOnlyToolError, FileNotFoundError) as exc:
        return f"(error: {exc})"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start_line = start or 1
    end_line = end or len(lines)
    selected = lines[start_line - 1 : end_line]
    capped = selected[:_MAX_READ_LINES]
    rendered = [
        f"{line_no}: {line[:1000]}"
        for line_no, line in enumerate(capped, start=start_line)
    ]
    if len(selected) > _MAX_READ_LINES:
        rendered.append(f"... capped at {_MAX_READ_LINES} lines")
    return "\n".join(rendered)
