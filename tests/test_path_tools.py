from pathlib import Path

import pytest

from agent.tools.path_tools import SafetyError, resolve_under


def test_resolve_under_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(SafetyError):
        resolve_under(tmp_path, "../outside")


def test_resolve_under_accepts_child(tmp_path: Path) -> None:
    child = tmp_path / "a.txt"
    child.write_text("ok", encoding="utf-8")

    assert resolve_under(tmp_path, "a.txt", must_exist=True) == child.resolve()

