from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from agent.tools.path_tools import ensure_existing_file_under


class ValidationError(RuntimeError):
    pass


def validate_script(validation_dir: str | Path, script_name: str) -> Path:
    script = ensure_existing_file_under(validation_dir, script_name)
    if not script.stat().st_mode & 0o111:
        raise ValidationError(f"Validation script is not executable: {script_name}")
    return script


def run_validation_script(
    *,
    validation_dir: str | Path,
    script_name: str,
    ssh_target: str,
    remote_dir: str,
    output_dir: str | Path,
    port: int = 22,
    timeout_sec: int = 300,
) -> dict[str, object]:
    script = validate_script(validation_dir, script_name)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stdout_path = output / "stdout.txt"
    stderr_path = output / "stderr.txt"
    remote_script = f"{remote_dir.rstrip('/')}/{script.name}"
    ssh_base = ["ssh", "-p", str(port), ssh_target]
    scp_target = f"{ssh_target}:{remote_script}"

    start = time.monotonic()
    mkdir = subprocess.run(
        [*ssh_base, f"mkdir -p {shlex.quote(remote_dir)}"],
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    if mkdir.returncode != 0:
        stdout_path.write_text(mkdir.stdout, encoding="utf-8")
        stderr_path.write_text(mkdir.stderr, encoding="utf-8")
        return _result("failed", mkdir.returncode, start, stdout_path, stderr_path)

    scp = subprocess.run(
        ["scp", "-P", str(port), str(script), scp_target],
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    if scp.returncode != 0:
        stdout_path.write_text(scp.stdout, encoding="utf-8")
        stderr_path.write_text(scp.stderr, encoding="utf-8")
        return _result("failed", scp.returncode, start, stdout_path, stderr_path)

    run = subprocess.run(
        [*ssh_base, f"chmod +x {shlex.quote(remote_script)} && {shlex.quote(remote_script)}"],
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )
    stdout_path.write_text(run.stdout, encoding="utf-8")
    stderr_path.write_text(run.stderr, encoding="utf-8")
    status = "success" if run.returncode == 0 else "failed"
    return _result(status, run.returncode, start, stdout_path, stderr_path)


def _result(
    status: str,
    returncode: int,
    start: float,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, object]:
    return {
        "status": status,
        "returncode": returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "duration_sec": round(time.monotonic() - start, 3),
    }
