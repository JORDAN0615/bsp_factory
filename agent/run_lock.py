from __future__ import annotations

from pathlib import Path


def _marker(runs_dir) -> Path:
    return Path(runs_dir) / ".webhook" / "active"


def acquire_active(runs_dir) -> bool:
    marker = _marker(runs_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return False
    return True


def release_active(runs_dir) -> None:
    _marker(runs_dir).unlink(missing_ok=True)


def is_active(runs_dir) -> bool:
    return _marker(runs_dir).exists()
