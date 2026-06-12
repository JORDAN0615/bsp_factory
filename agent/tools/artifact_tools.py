from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def slugify(text: str, max_len: int = 40) -> str:
    chars: list[str] = []
    for char in text.lower():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "_":
            chars.append("_")
    slug = "".join(chars).strip("_")
    return (slug or "run")[:max_len].strip("_") or "run"


def make_run_id(issue: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{ts}_{slugify(issue)}"


def attempt_dir(run_dir: str | Path, attempt_no: int) -> Path:
    path = Path(run_dir) / "attempts" / f"{attempt_no:03d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validation_run_dir(attempt_path: str | Path, index: int, script_name: str) -> Path:
    stem = slugify(Path(script_name).stem, max_len=60)
    path = Path(attempt_path) / "validation_runs" / f"{index:03d}_{stem}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: str | Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text(path: str | Path, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def copy_input_log(src: Path, run_dir: Path) -> str:
    dst = run_dir / "raw_logs" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    return str(dst)

