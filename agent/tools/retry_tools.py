from __future__ import annotations

import re
from pathlib import Path

from agent.state import BSPAgentState, RepairAttempt, ValidationRunInfo
from agent.tools.artifact_tools import attempt_dir
from agent.tools.patch_tools import PatchError, extract_diff_from_patch_md


_TAIL_MAX_LINES = 10
_TAIL_MAX_CHARS = 800
_FEEDBACK_MAX_CHARS = 1000
_PATCH_EXCERPT_MAX_CHARS = 1000


def build_retry_context(state: BSPAgentState) -> str:
    """Build the retry context block for the current attempt at runtime.

    The context is generated from state.json data and previous attempts'
    artifacts on disk (patch.md, no_patch.md, validation outputs). No memory
    files are written. The current in-progress attempt never appears in its
    own retry context.
    """
    current_no = state.current_attempt.attempt_no
    previous = [attempt for attempt in state.attempts if attempt.attempt_no < current_no]
    header = [
        "# Retry Context",
        "",
        f"Run: `{state.run_id}`",
        "",
    ]
    if not previous:
        return "\n".join(header + ["(No previous attempts in this run.)", ""])
    header.extend(
        [
            "Summaries of previous attempts in this run. Do not repeat patches that",
            "were rejected by human review or that failed validation.",
            "",
        ]
    )
    sections: list[str] = []
    for attempt in previous:
        sections.append(_render_attempt(state, attempt).rstrip())
        sections.append("")
    return "\n".join(header + sections)


def _render_attempt(state: BSPAgentState, attempt: RepairAttempt) -> str:
    path = attempt_dir(state.run_dir, attempt.attempt_no)
    lines = [
        f"## Attempt {attempt.attempt_no:03d}",
        "",
        f"- Bug type: `{attempt.bug_type or 'unknown'}`",
        f"- Selected skills: `{', '.join(attempt.selected_skills) or 'none'}`",
        f"- Patch status: `{attempt.patch_status}`",
        f"- Changed files: `{', '.join(attempt.changed_files) or 'none'}`",
        f"- Human review: `{attempt.human_review_status}`",
    ]
    if attempt.code_review_decision:
        lines.append(f"- Code review decision: `{attempt.code_review_decision}`")
        for finding in attempt.code_review_findings:
            lines.append(f"- Code review finding: {_one_line(finding, _FEEDBACK_MAX_CHARS)}")
        for change in attempt.code_review_required_changes:
            lines.append(f"- Code review required change: {_one_line(change, _FEEDBACK_MAX_CHARS)}")
    if attempt.human_feedback:
        lines.append(f"- Human feedback: {_one_line(attempt.human_feedback, _FEEDBACK_MAX_CHARS)}")
    no_patch_reason = _no_patch_reason(path)
    if no_patch_reason:
        lines.append(
            f"- No-patch / failure reason: {_one_line(no_patch_reason, _FEEDBACK_MAX_CHARS)}"
        )
    if attempt.build_status:
        lines.append(f"- Target build ({attempt.build_scope or 'full'}): `{attempt.build_status}`")
    lines.append("")
    patch_excerpt = _patch_excerpt(path)
    if patch_excerpt:
        lines.extend(["Patch excerpt:", "", "```diff", patch_excerpt, "```", ""])
    if attempt.build_status == "failed":
        build_tail = _tail_summary(attempt.build_log_path)
        if build_tail:
            lines.extend(["Build failure (fix this before re-editing):", "", "```text", build_tail, "```", ""])
    for run in attempt.validation_runs:
        lines.extend(_render_validation(run))
    return "\n".join(lines).rstrip() + "\n"


def _render_validation(run: ValidationRunInfo) -> list[str]:
    lines = [
        f"### Validation `{run.validation_id}`",
        "",
        f"- Script: `{run.script}`",
        f"- Status: `{run.status}` (exit `{run.returncode}`)",
        "",
    ]
    for stream, path in (("stdout", run.stdout_path), ("stderr", run.stderr_path)):
        summary = _tail_summary(path)
        if summary:
            lines.extend([f"{stream} tail:", "", "```text", summary, "```", ""])
    return lines


def _patch_excerpt(attempt_path: Path) -> str | None:
    patch = attempt_path / "patch.md"
    if not patch.exists():
        return None
    try:
        diff = extract_diff_from_patch_md(patch.read_text(errors="replace", encoding="utf-8"))
    except PatchError:
        return None
    return diff.strip()[:_PATCH_EXCERPT_MAX_CHARS] or None


def _no_patch_reason(attempt_path: Path) -> str | None:
    no_patch = attempt_path / "no_patch.md"
    if not no_patch.exists():
        return None
    text = no_patch.read_text(errors="replace", encoding="utf-8")
    match = re.search(r"^## Reason\n+(.*?)(?:\n## |\Z)", text, re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1).strip() or None
    return text.strip() or None


def _tail_summary(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    text = Path(path).read_text(errors="replace", encoding="utf-8").strip()
    if not text:
        return None
    tail = "\n".join(text.splitlines()[-_TAIL_MAX_LINES:])
    return tail[-_TAIL_MAX_CHARS:]


def _one_line(text: str, max_chars: int) -> str:
    return " ".join(str(text).split())[:max_chars]
