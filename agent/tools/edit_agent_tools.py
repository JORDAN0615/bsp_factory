from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path, PurePath
from collections.abc import Iterator

from langchain_core.tools import tool


_edit_root: ContextVar[Path | None] = ContextVar("editable_repo_root", default=None)


@contextmanager
def editable_repo(staging_path: str | Path) -> Iterator[None]:
    root = Path(staging_path).resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"editable repo path is not a directory: {staging_path}")
    token = _edit_root.set(root)
    try:
        yield
    finally:
        _edit_root.reset(token)


def _current_root() -> Path:
    root = _edit_root.get()
    if root is None:
        raise RuntimeError("editable repo root is not configured")
    return root


def _resolve_file(path: str) -> Path:
    root = _current_root()
    if not path.strip():
        raise RuntimeError("path is required")
    if ".." in PurePath(path).parts:
        raise RuntimeError("path may not contain '..'")
    candidate = Path(path)
    if candidate.is_absolute():
        raise RuntimeError("path must be repo-relative")
    resolved = (root / candidate).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"path escapes editable repo root: {path}")
    if not resolved.is_file():
        raise RuntimeError(f"path is not a file: {path}")
    return resolved


def replace_in_editable_repo(
    path: str,
    search: str,
    replace: str,
    replace_all: bool = False,
) -> str:
    """Replace exact text in the scoped staging repo without raising into an agent loop."""
    try:
        file_path = _resolve_file(path)
        content = file_path.read_text(errors="replace", encoding="utf-8")
        count = content.count(search)
        if count == 0:
            return "(error: SEARCH not found; read_file first and copy exact lines)"
        if count > 1 and not replace_all:
            return f"(error: SEARCH appears {count} times; add context or set replace_all=true)"
        new_content = content.replace(search, replace, -1 if replace_all else 1)
        file_path.write_text(new_content, encoding="utf-8")
        return f"(ok: replaced {count if replace_all else 1})"
    except Exception as exc:  # noqa: BLE001
        return f"(error: {exc})"


@tool
def edit_file(path: str, search: str, replace: str, replace_all: bool = False) -> str:
    """Replace exact text in a file under the current editable staging repo."""
    return replace_in_editable_repo(path, search, replace, replace_all)
