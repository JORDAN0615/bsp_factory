from __future__ import annotations

from pathlib import Path


class SafetyError(ValueError):
    """Raised when a path violates the agent safety boundary."""


def require_relative_path(path: str | Path) -> Path:
    rel = Path(path)
    if rel.is_absolute():
        raise SafetyError(f"Absolute paths are not allowed: {path}")
    if any(part == ".." for part in rel.parts):
        raise SafetyError(f"Parent traversal is not allowed: {path}")
    return rel


def resolve_under(root: str | Path, relative_path: str | Path, must_exist: bool = False) -> Path:
    root_path = Path(root).resolve()
    rel = require_relative_path(relative_path)
    full = (root_path / rel).resolve()
    if root_path != full and root_path not in full.parents:
        raise SafetyError(f"Path escapes root: {relative_path}")
    if must_exist and not full.exists():
        raise FileNotFoundError(full)
    return full


def ensure_existing_file_under(root: str | Path, relative_path: str | Path) -> Path:
    full = resolve_under(root, relative_path, must_exist=True)
    if not full.is_file():
        raise SafetyError(f"Expected file: {relative_path}")
    return full

