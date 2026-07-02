from pathlib import Path

import pytest

from agent.tools.edit_tools import (
    EditBlock,
    EditError,
    apply_edits,
    parse_edit_blocks,
    preview_diff,
)


def test_parse_and_apply_unique_match(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    blocks = parse_edit_blocks(
        """FILE: board.dts
<<<<<<< SEARCH
status = "disabled";
=======
status = "okay";
>>>>>>> REPLACE
"""
    )

    result = apply_edits(tmp_path, blocks, write=True)

    assert result["board.dts"] == 'status = "okay";\n'
    assert (tmp_path / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'


def test_apply_edits_rejects_missing_search(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text("current\n", encoding="utf-8")

    with pytest.raises(EditError, match="SEARCH not found"):
        apply_edits(
            tmp_path,
            [EditBlock(file="board.dts", search="missing", replace="new")],
            write=False,
        )


def test_apply_edits_rejects_ambiguous_search_without_replace_all(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text("same\nsame\n", encoding="utf-8")

    with pytest.raises(EditError, match="SEARCH appears 2 times"):
        apply_edits(
            tmp_path,
            [EditBlock(file="board.dts", search="same", replace="new")],
            write=False,
        )


def test_apply_edits_replace_all(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text("same\nsame\n", encoding="utf-8")

    result = apply_edits(
        tmp_path,
        [EditBlock(file="board.dts", search="same", replace="new", replace_all=True)],
        write=False,
    )

    assert result["board.dts"] == "new\nnew\n"


def test_apply_edits_composes_multiple_blocks_same_file(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text("a\nb\nc\n", encoding="utf-8")
    blocks = [
        EditBlock(file="board.dts", search="a", replace="aa"),
        EditBlock(file="board.dts", search="c", replace="cc"),
    ]

    result = apply_edits(tmp_path, blocks, write=False)

    assert result["board.dts"] == "aa\nb\ncc\n"
    assert (tmp_path / "board.dts").read_text(encoding="utf-8") == "a\nb\nc\n"


def test_apply_edits_rejects_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")

    with pytest.raises(EditError, match="may not contain"):
        apply_edits(
            tmp_path,
            [EditBlock(file="../outside.txt", search="old", replace="new")],
            write=False,
        )


def test_preview_diff_returns_unified_diff(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")

    diff = preview_diff(
        tmp_path,
        [EditBlock(file="board.dts", search='status = "disabled";', replace='status = "okay";')],
    )

    assert "--- a/board.dts" in diff
    assert "+++ b/board.dts" in diff
    assert '-status = "disabled";' in diff
    assert '+status = "okay";' in diff
