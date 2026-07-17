from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent.tools.git_tools import add_worktree, remove_worktree
from agent.tools.patch_tools import apply_patch

if TYPE_CHECKING:
    from agent.config import Settings


@dataclass
class BuildResult:
    """Outcome of one BSP build (ADR-0018/0019).

    ``ran`` distinguishes "the build executed and failed" (a normal repair
    signal that should feed the next attempt) from "the build could not start"
    (an infrastructure problem — missing entrypoint, timeout — that should pause
    for a human instead of burning a repair attempt).
    """

    ok: bool
    ran: bool
    returncode: int
    log_path: Path


def _entrypoint_path(settings: "Settings") -> Path:
    entry = Path(settings.build_entrypoint)
    return entry if entry.is_absolute() else (Path.cwd() / entry)


def run_bsp_build(
    repo_path: str | Path,
    diff_text: str,
    scope: str,
    settings: "Settings",
    log_path: str | Path,
) -> BuildResult:
    """Apply ``diff_text`` to a throwaway staging worktree and build it.

    The real working tree is never touched here — the gate must not mutate it
    before human approval. The build entrypoint (``BUILD_ENTRYPOINT``) is the
    team-owned ``build_bsp.sh`` that glues the overlay into the framework project
    and runs the framework build; the agent only reads its exit code and log.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entrypoint = _entrypoint_path(settings)

    if not entrypoint.exists():
        log_path.write_text(
            f"(build could not start: entrypoint not found: {entrypoint})\n",
            encoding="utf-8",
        )
        return BuildResult(ok=False, ran=False, returncode=127, log_path=log_path)

    staging_path = Path(tempfile.mkdtemp(prefix=f"bsp-build-{Path(repo_path).name}-"))
    try:
        staging_path.rmdir()
    except OSError:
        pass
    staging = str(staging_path)

    ran = False
    returncode = 1
    output = ""
    try:
        add_worktree(repo_path, staging)
        if diff_text.strip():
            apply_patch(staging, diff_text)
        proc = subprocess.run(
            [str(entrypoint), staging, scope],
            capture_output=True,
            text=True,
            timeout=settings.build_timeout_sec,
            check=False,
        )
        ran = True
        returncode = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        output = (
            f"(build timed out after {settings.build_timeout_sec}s)\n"
            f"{exc.stdout or ''}{exc.stderr or ''}"
        )
        returncode = 124
    except Exception as exc:  # noqa: BLE001 - surface any staging/apply failure in the log
        output = f"(build could not start: {exc})\n"
        returncode = 1
    finally:
        remove_worktree(repo_path, staging)
        shutil.rmtree(staging, ignore_errors=True)

    log_path.write_text(output, encoding="utf-8")
    return BuildResult(ok=(ran and returncode == 0), ran=ran, returncode=returncode, log_path=log_path)
