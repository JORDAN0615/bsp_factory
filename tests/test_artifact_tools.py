from pathlib import Path

from agent.tools.artifact_tools import attempt_dir, make_run_id, validation_run_dir


def test_attempt_and_validation_dirs(tmp_path: Path) -> None:
    run_id = make_run_id("Camera probe failed!")
    assert "camera_probe_failed" in run_id

    attempt = attempt_dir(tmp_path, 1)
    validation = validation_run_dir(attempt, 1, "camera_check.sh")

    assert attempt.name == "001"
    assert validation.name == "001_camera_check"

