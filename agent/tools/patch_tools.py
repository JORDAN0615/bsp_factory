from __future__ import annotations

import re
import subprocess
from pathlib import Path

from agent.tools.git_tools import get_git_diff, run_git


class PatchError(RuntimeError):
    pass


_CONTEXT_LINES = 3
_CONTEXT_TRIM_LIMIT = 3


def validate_unified_diff(diff_text: str, allow_new_files: bool = False) -> None:
    stripped = diff_text.strip()
    if not stripped:
        raise PatchError("Patch is empty.")
    if stripped == "NO_PATCH" or stripped.startswith("NO_PATCH"):
        raise PatchError("NO_PATCH is not a unified diff.")
    if "@@" not in diff_text:
        raise PatchError("Unified diff must contain hunk markers.")
    if not re.search(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", diff_text, re.MULTILINE):
        raise PatchError("Unified diff hunk markers must include line numbers.")
    if "diff --git " not in diff_text and ("--- " not in diff_text or "+++ " not in diff_text):
        raise PatchError("Unified diff must contain file headers.")
    if not allow_new_files and ("/dev/null" in diff_text or "new file mode" in diff_text):
        raise PatchError("MVP does not allow patches that create files.")


def apply_patch(repo_path: str | Path, diff_text: str) -> None:
    diff_text = _ensure_trailing_newline(diff_text)
    validate_unified_diff(diff_text)
    check = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--check"],
        input=diff_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        raise PatchError(check.stderr.strip() or "git apply --check failed")
    apply = subprocess.run(
        ["git", "-C", str(repo_path), "apply"],
        input=diff_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if apply.returncode != 0:
        raise PatchError(apply.stderr.strip() or "git apply failed")


def normalize_hunk_headers(repo_path: str | Path, diff_text: str) -> str:
    diff_text = _ensure_trailing_newline(diff_text)
    lines = diff_text.splitlines()
    output: list[str] = []
    current_file: str | None = None
    index = 0
    changed = False
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            current_file = _path_from_header(line)
            output.append(line)
            index += 1
            continue
        if line.startswith("@@"):
            if not current_file:
                raise PatchError("Cannot normalize hunk without file header.")
            hunk: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith(
                ("diff --git ", "--- ", "@@")
            ):
                hunk.append(lines[index])
                index += 1
            hunk = [" " if item == "" else item for item in hunk]
            file_path = Path(repo_path) / current_file
            content = file_path.read_text(errors="replace", encoding="utf-8").splitlines()
            hunk, old_lines, new_lines, old_start, file_block = _match_hunk_with_trim(
                file_path, content, hunk
            )
            if file_block != old_lines:
                hunk = _rewrite_hunk(hunk, file_block)
            old_count = len(old_lines)
            new_count = len(new_lines)
            # git apply rejects hunks without surrounding context; pad missing
            # context from the file itself.
            if hunk and not hunk[0].startswith(" "):
                pre = content[max(0, old_start - 1 - _CONTEXT_LINES) : old_start - 1]
                hunk = [" " + item for item in pre] + hunk
                old_start -= len(pre)
                old_count += len(pre)
                new_count += len(pre)
            if hunk and not hunk[-1].startswith(" "):
                end = old_start - 1 + old_count
                post = content[end : end + _CONTEXT_LINES]
                hunk = hunk + [" " + item for item in post]
                old_count += len(post)
                new_count += len(post)
            output.append(f"@@ {_range_header('-', old_start, old_count)} {_range_header('+', old_start, new_count)} @@")
            output.extend(hunk)
            changed = True
            continue
        output.append(line)
        index += 1
    if not changed:
        return diff_text
    return _ensure_trailing_newline("\n".join(output))


def reverse_patch(repo_path: str | Path, diff_text: str) -> None:
    diff_text = _ensure_trailing_newline(diff_text)
    check = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--reverse", "--check"],
        input=diff_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        raise PatchError(check.stderr.strip() or "git apply --reverse --check failed")
    apply = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--reverse"],
        input=diff_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if apply.returncode != 0:
        raise PatchError(apply.stderr.strip() or "git apply --reverse failed")


def extract_diff_from_patch_md(text: str) -> str:
    """Extract the unified diff from the canonical patch.md artifact."""
    match = re.search(r"```diff\n(.*?)```", text, re.DOTALL)
    if not match:
        raise PatchError("patch.md does not contain a fenced diff block.")
    diff = match.group(1)
    if not diff.strip():
        raise PatchError("patch.md diff block is empty.")
    return _ensure_trailing_newline(diff)


def summarize_changed_files(repo_path: str | Path) -> list[dict[str, object]]:
    result = run_git(repo_path, ["diff", "--numstat"]).stdout
    summary: list[dict[str, object]] = []
    for line in result.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        additions, deletions, file_name = parts
        summary.append(
            {
                "file": file_name,
                "additions": None if additions == "-" else int(additions),
                "deletions": None if deletions == "-" else int(deletions),
            }
        )
    if not summary:
        summary = [{"file": file_name, "additions": None, "deletions": None} for file_name in changed_files_from_diff(get_git_diff(repo_path))]
    return summary


def summarize_diff(diff_text: str) -> list[dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                current = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                summary[current] = {"file": current, "additions": 0, "deletions": 0}
            continue
        if line.startswith("+++ ") and current is None:
            current = _path_from_header(line)
            if current:
                summary[current] = {"file": current, "additions": 0, "deletions": 0}
            continue
        if not current or line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            summary[current]["additions"] = int(summary[current]["additions"]) + 1
        elif line.startswith("-"):
            summary[current]["deletions"] = int(summary[current]["deletions"]) + 1
    return list(summary.values())


def changed_files_from_diff(diff_text: str) -> list[str]:
    files: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) >= 4:
            file_name = parts[3]
            if file_name.startswith("b/"):
                file_name = file_name[2:]
            files.append(file_name)
    if files:
        return files
    for line in diff_text.splitlines():
        if not line.startswith("+++ "):
            continue
        file_name = _path_from_header(line)
        if file_name:
            files.append(file_name)
    return files


def _path_from_header(line: str) -> str | None:
    path = line.split(maxsplit=1)[1]
    if path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _strip_diff_prefix(line: str) -> str:
    return line[1:] if line and line[0] in {" ", "+", "-"} else line


def _match_hunk_with_trim(
    path: Path, content: list[str], hunk: list[str]
) -> tuple[list[str], list[str], list[str], int, list[str]]:
    """Match the hunk's old block in the file, trimming a few leading or
    trailing context lines when the LLM invented context that does not exist
    (for example a blank line or extra closing braces). The remaining block
    must still match uniquely."""
    last_error: PatchError | None = None
    for front in range(_CONTEXT_TRIM_LIMIT + 1):
        if front and not _is_context_line(hunk[front - 1]):
            break
        for back in range(_CONTEXT_TRIM_LIMIT + 1):
            if front + back >= len(hunk):
                break
            if back and not _is_context_line(hunk[len(hunk) - back]):
                break
            candidate = hunk[front : len(hunk) - back] if back else hunk[front:]
            old_lines = [_strip_diff_prefix(item) for item in candidate if item.startswith(("-", " "))]
            new_lines = [_strip_diff_prefix(item) for item in candidate if item.startswith(("+", " "))]
            if not old_lines:
                continue
            try:
                old_start, file_block = _find_unique_block(path, content, old_lines)
            except PatchError as exc:
                last_error = exc
                continue
            return candidate, old_lines, new_lines, old_start, file_block
    raise last_error or PatchError(f"Cannot normalize hunk in {path}.")


def _is_context_line(line: str) -> bool:
    return line.startswith(" ")


def _find_unique_block(path: Path, content: list[str], old_lines: list[str]) -> tuple[int, list[str]]:
    if not old_lines:
        raise PatchError("Cannot normalize empty old hunk.")
    size = len(old_lines)
    for compare in (_exact_line, _normalized_line):
        wanted = [compare(item) for item in old_lines]
        matches = [
            index
            for index in range(0, len(content) - size + 1)
            if [compare(item) for item in content[index : index + size]] == wanted
        ]
        if len(matches) > 1:
            raise PatchError(f"Cannot normalize hunk; old block is ambiguous in {path}.")
        if matches:
            start = matches[0]
            return start + 1, content[start : start + size]
    raise PatchError(f"Cannot normalize hunk; old block not found in {path}.")


def _rewrite_hunk(hunk: list[str], file_block: list[str]) -> list[str]:
    """Rewrite a whitespace-relaxed hunk so its old side matches the file exactly.

    Context and removed lines take the exact file content. Added lines whose
    whitespace-normalized content already exists uniquely in the matched block
    adopt that file line verbatim (fixing LLM indentation drift); genuinely new
    lines are kept as proposed.
    """
    rewritten: list[str] = []
    old_index = 0
    for item in hunk:
        if item.startswith(("-", " ")):
            rewritten.append(item[0] + file_block[old_index])
            old_index += 1
        elif item.startswith("+"):
            rewritten.append("+" + _fix_added_line(item[1:], file_block))
        else:
            rewritten.append(item)
    return rewritten


def _fix_added_line(content: str, file_block: list[str]) -> str:
    normalized = _normalized_line(content)
    if not normalized:
        return content
    candidates = [line for line in file_block if _normalized_line(line) == normalized]
    if len(candidates) == 1:
        return candidates[0]
    return content


def _exact_line(line: str) -> str:
    return line


def _normalized_line(line: str) -> str:
    return " ".join(line.split())


def _range_header(prefix: str, start: int, count: int) -> str:
    if count == 1:
        return f"{prefix}{start}"
    return f"{prefix}{start},{count}"


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"
