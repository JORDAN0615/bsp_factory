from pathlib import Path

from agent.tools.edit_agent_tools import edit_file, editable_repo


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "board.dts").write_text("old\nsame\nsame\n", encoding="utf-8")
    return repo


def test_edit_file_replaces_unique_match(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with editable_repo(repo):
        result = edit_file.invoke({"path": "board.dts", "search": "old", "replace": "new"})

    assert result == "(ok: replaced 1)"
    assert (repo / "board.dts").read_text(encoding="utf-8") == "new\nsame\nsame\n"


def test_edit_file_returns_error_when_search_missing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with editable_repo(repo):
        result = edit_file.invoke({"path": "board.dts", "search": "missing", "replace": "new"})

    assert "SEARCH not found" in result


def test_edit_file_returns_error_when_ambiguous(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with editable_repo(repo):
        result = edit_file.invoke({"path": "board.dts", "search": "same", "replace": "new"})

    assert "SEARCH appears 2 times" in result


def test_edit_file_replace_all(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with editable_repo(repo):
        result = edit_file.invoke(
            {"path": "board.dts", "search": "same", "replace": "new", "replace_all": True}
        )

    assert result == "(ok: replaced 2)"
    assert (repo / "board.dts").read_text(encoding="utf-8") == "old\nnew\nnew\n"


def test_edit_file_sandbox_error_returns_string(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with editable_repo(repo):
        result = edit_file.invoke({"path": "../outside.txt", "search": "old", "replace": "new"})

    assert "error" in result
    assert "path may not contain" in result
