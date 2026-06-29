from pathlib import Path

import pytest

from agent.tools.readonly_tools import grep_repo, read_file, readonly_repo


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "drivers").mkdir()
    (repo / "drivers" / "camera.c").write_text("probe failed\nneedle\n", encoding="utf-8")
    (repo / "board.dts").write_text('status = "disabled";\nneedle\n', encoding="utf-8")
    return repo


def test_grep_repo_searches_inside_repo_and_caps_results(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    big = repo / "big.txt"
    big.write_text("\n".join(f"needle {index}" for index in range(250)), encoding="utf-8")

    with readonly_repo(repo):
        result = grep_repo.invoke({"pattern": "needle"})

    lines = result.splitlines()
    assert any("board.dts" in line for line in lines)
    assert len(lines) <= 201
    assert lines[-1] == "... capped at 200 lines"


def test_read_file_returns_line_numbered_slice_and_caps(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "long.txt").write_text("\n".join(f"line {index}" for index in range(500)), encoding="utf-8")

    with readonly_repo(repo):
        sliced = read_file.invoke({"path": "board.dts", "start": 2, "end": 2})
        capped = read_file.invoke({"path": "long.txt"})

    assert sliced == "2: needle"
    assert len(capped.splitlines()) == 401
    assert capped.splitlines()[-1] == "... capped at 400 lines"


@pytest.mark.parametrize("bad_path", ["../outside.txt", "/tmp"])
def test_readonly_tools_refuse_outside_paths(tmp_path: Path, bad_path: str) -> None:
    repo = make_repo(tmp_path)

    with readonly_repo(repo):
        result = read_file.invoke({"path": bad_path})

    assert "error" in result


def test_readonly_tools_refuse_symlink_escape(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (repo / "escape.txt").symlink_to(outside)

    with readonly_repo(repo):
        result = read_file.invoke({"path": "escape.txt"})

    assert "error" in result


def test_readonly_tools_do_not_write(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    before = sorted(path.relative_to(repo) for path in repo.rglob("*"))

    with readonly_repo(repo):
        grep_repo.invoke({"pattern": "needle"})
        read_file.invoke({"path": "board.dts"})

    after = sorted(path.relative_to(repo) for path in repo.rglob("*"))
    assert after == before
