from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from agent.tools.path_tools import ensure_existing_file_under, resolve_under

_rg_available: bool | None = None


def _has_rg() -> bool:
    global _rg_available
    if _rg_available is None:
        _rg_available = shutil.which("rg") is not None
    return _rg_available


def _grep_python(root: Path, pattern: str, include: str | None) -> list[dict[str, object]]:
    """Pure-Python fallback for grep_repo when ripgrep is not installed."""
    glob_pat = include or "*"
    if glob_pat.startswith("**/"):
        glob_pat = glob_pat[3:]
    matches: list[dict[str, object]] = []
    for path in root.rglob(glob_pat):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if pattern in line:
                try:
                    rel = str(path.relative_to(root))
                except ValueError:
                    rel = str(path)
                matches.append({"file": rel, "line": i, "text": line})
    return matches


def read_text_file(repo_path: str | Path, relative_path: str | Path, max_chars: int = 20000) -> str:
    path = ensure_existing_file_under(repo_path, relative_path)
    return path.read_text(errors="replace", encoding="utf-8")[:max_chars]


def write_text_file(repo_path: str | Path, relative_path: str | Path, content: str) -> None:
    path = resolve_under(repo_path, relative_path, must_exist=True)
    if not path.is_file():
        raise ValueError(f"Expected existing file: {relative_path}")
    path.write_text(content, encoding="utf-8")


def grep_repo(repo_path: str | Path, pattern: str, include: str | None = None) -> list[dict[str, object]]:
    if "\n" in pattern or not pattern.strip():
        return []
    root = Path(repo_path)

    if not _has_rg():
        return _grep_python(root, pattern, include)

    cmd = ["rg", "--fixed-strings", "--line-number", "--no-heading", "--", pattern, str(root)]
    if include:
        cmd[1:1] = ["--glob", include]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip())
    matches: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        file_path, line_no, text = parts
        try:
            rel = str(Path(file_path).resolve().relative_to(root.resolve()))
        except ValueError:
            rel = file_path
        matches.append({"file": rel, "line": int(line_no), "text": text})
    return matches


def list_candidate_files(repo_path: str | Path, keywords: list[str], limit: int = 20) -> list[str]:
    include_globs = [
        "*.dts",
        "*.dtsi",
        "*defconfig",
        "Kconfig",
        "Makefile",
        "*.c",
        "*.h",
    ]
    found: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        for glob in include_globs:
            for match in grep_repo(repo_path, keyword, include=glob):
                file_name = str(match["file"])
                if file_name not in seen:
                    seen.add(file_name)
                    found.append(file_name)
                    if len(found) >= limit:
                        return found
    return found
