from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import Path, PurePath


class EditError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditBlock:
    file: str
    search: str
    replace: str
    replace_all: bool = False


def parse_edit_blocks(text: str) -> list[EditBlock]:
    lines = text.splitlines()
    blocks: list[EditBlock] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("FILE:"):
            if lines[index].strip():
                raise EditError(f"Malformed edit block near line {index + 1}: expected FILE")
            index += 1
            continue
        file_name = lines[index].split(":", 1)[1].strip()
        if not file_name:
            raise EditError(f"Malformed edit block near line {index + 1}: FILE path is required")
        index += 1
        replace_all = False
        if index < len(lines) and lines[index].startswith("REPLACE_ALL:"):
            value = lines[index].split(":", 1)[1].strip().lower()
            if value not in {"true", "false"}:
                raise EditError(f"Malformed edit block near line {index + 1}: REPLACE_ALL must be true or false")
            replace_all = value == "true"
            index += 1
        if index >= len(lines) or lines[index].strip() != "<<<<<<< SEARCH":
            raise EditError(f"Malformed edit block near line {index + 1}: expected <<<<<<< SEARCH")
        index += 1
        search_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != "=======":
            search_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            raise EditError(f"Malformed edit block for {file_name}: missing =======")
        index += 1
        replace_lines: list[str] = []
        while index < len(lines) and lines[index].strip() != ">>>>>>> REPLACE":
            replace_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            raise EditError(f"Malformed edit block for {file_name}: missing >>>>>>> REPLACE")
        index += 1
        search = "\n".join(search_lines)
        replace = "\n".join(replace_lines)
        if not search:
            raise EditError(f"Malformed edit block for {file_name}: SEARCH must not be empty")
        blocks.append(EditBlock(file=file_name, search=search, replace=replace, replace_all=replace_all))
    if not blocks:
        raise EditError("No edit blocks found.")
    return blocks


def apply_edits(repo_path: str | Path, blocks: list[EditBlock], *, write: bool) -> dict[str, str]:
    if not blocks:
        raise EditError("No edit blocks to apply.")
    root = Path(repo_path).resolve(strict=True)
    accumulated: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for block in blocks:
        relative_path, file_path = _resolve_file(root, block.file)
        current = accumulated.get(relative_path)
        if current is None:
            current = file_path.read_text(errors="replace", encoding="utf-8")
        count = current.count(block.search)
        if count == 0:
            raise EditError(f"SEARCH not found in {relative_path}; paste the exact current lines")
        if count > 1 and not block.replace_all:
            raise EditError(
                f"SEARCH appears {count} times in {relative_path}; add surrounding context "
                "to make it unique, or set REPLACE_ALL: true"
            )
        accumulated[relative_path] = current.replace(
            block.search,
            block.replace,
            -1 if block.replace_all else 1,
        )
        paths[relative_path] = file_path
    if write:
        for relative_path, content in accumulated.items():
            paths[relative_path].write_text(content, encoding="utf-8")
    return accumulated


def preview_diff(repo_path: str | Path, blocks: list[EditBlock]) -> str:
    new_contents = apply_edits(repo_path, blocks, write=False)
    root = Path(repo_path).resolve(strict=True)
    chunks: list[str] = []
    for relative_path, new_content in new_contents.items():
        old_content = (root / relative_path).read_text(errors="replace", encoding="utf-8")
        if old_content == new_content:
            continue
        chunks.extend(
            difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
    if not chunks:
        raise EditError("Edit blocks produced no changes.")
    diff = "\n".join(chunks)
    return diff if diff.endswith("\n") else f"{diff}\n"


def _resolve_file(root: Path, path: str) -> tuple[str, Path]:
    if not path.strip():
        raise EditError("FILE path is required")
    if ".." in PurePath(path).parts:
        raise EditError("FILE path may not contain '..'")
    candidate = Path(path)
    if candidate.is_absolute():
        raise EditError("FILE path must be repo-relative")
    resolved = (root / candidate).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise EditError(f"FILE path escapes repo root: {path}")
    if not resolved.is_file():
        raise EditError(f"FILE does not exist: {path}")
    relative_path = resolved.relative_to(root).as_posix()
    return relative_path, resolved
