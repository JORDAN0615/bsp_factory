from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax

from agent import run_lock
from agent.config import Settings
from agent.state import BSPAgentState, RepairAttempt, TargetInfo, ValidationRunInfo, now_iso
from agent.tools.artifact_tools import (
    attempt_dir,
    copy_input_log,
    make_run_id,
    validation_run_dir,
    write_json,
    write_text,
)
from agent.tools.git_tools import (
    branch_exists,
    checkout_branch,
    current_branch,
    delete_branch,
    ensure_clean_source,
    ensure_git_repo,
    pull_ff_only,
    run_git,
)
from agent.tools.llm_tools import LLMConfig, LLMError, chat_completion
from agent.tools.patch_tools import PatchError, extract_diff_from_patch_md
from agent.tools.repo_tools import read_text_file
from agent.tools.retry_tools import build_retry_context
from agent.tools.test_tools import run_validation_script


console = Console()


def create_run(
    repo: Path,
    issue: str,
    logs: list[Path],
    settings: Settings,
    issue_notes_url: str | None = None,
) -> BSPAgentState:
    ensure_git_repo(repo)
    ensure_clean_source(repo)

    run_id = make_run_id(issue)
    base_branch = _prepare_managed_branch(repo, run_id, settings)
    run_dir = settings.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    copied_logs = [copy_input_log(log, run_dir) for log in logs]
    write_text(run_dir / "input.md", _input_markdown(issue, copied_logs))

    state = BSPAgentState(
        run_id=run_id,
        repo_path=str(repo.resolve()),
        run_dir=str(run_dir),
        issue=issue,
        input_logs=copied_logs,
        max_loops=settings.max_loops,
        managed_base_branch=base_branch,
        issue_notes_url=issue_notes_url,
    )
    state.new_attempt()
    state.save()
    _run_repair_pipeline(state, settings)
    state = BSPAgentState.load(run_dir)
    if state.stage == "report":
        _cleanup_managed_branch(state, settings)
        generate_report(run_dir)
        return BSPAgentState.load(run_dir)
    return state


def approve_run(run_dir: str | Path, settings: Settings) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    attempt = state.current_attempt
    if attempt.patch_status != "generated":
        raise RuntimeError(
            f"Attempt is not ready for approval (patch status: {attempt.patch_status})."
        )
    from agent.graph import resume_review_graph

    state = resume_review_graph(state, settings, {"action": "approve"})
    if state.stage == "published":
        _post_publish_note(state, settings)
    if state.issue_notes_url and state.stage in {"published", "publish_failed"}:
        run_lock.release_active(settings.runs_dir)
    return state


def publish_run(run_dir: str | Path, settings: Settings) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    if state.stage != "publish_failed":
        raise RuntimeError(f"Run is not waiting for publish retry: {state.stage}")
    from agent.graph import _do_publish

    state = _do_publish(state, settings)
    if state.stage == "published":
        _post_publish_note(state, settings)
        run_lock.release_active(settings.runs_dir)
    return state


def abandon_run(run_dir: str | Path, settings: Settings) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    if state.stage != "publish_failed":
        raise RuntimeError(f"Run is not waiting for abandon: {state.stage}")
    run_git(state.repo_path, ["reset", "--hard"])
    run_git(state.repo_path, ["clean", "-fd"])
    _cleanup_managed_branch(state, settings)
    state.stage = "report"
    state.touch()
    state.save()
    run_lock.release_active(settings.runs_dir)
    return state


def reject_run(run_dir: str | Path, feedback: str, settings: Settings) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    from agent.graph import resume_review_graph

    state = resume_review_graph(state, settings, {"action": "reject", "feedback": feedback})
    if state.stage == "report":
        _cleanup_managed_branch(state, settings)
        generate_report(Path(state.run_dir))
        if state.issue_notes_url:
            run_lock.release_active(settings.runs_dir)
        return BSPAgentState.load(run_dir)
    return state


def _post_publish_note(state: BSPAgentState, settings: Settings) -> None:
    if not state.issue_notes_url:
        return
    from agent.tools.gitlab_tools import post_issue_note

    summary = (
        f"BSP agent patch for run `{state.run_id}` was approved, committed, "
        f"and pushed to `{state.current_attempt.published_branch}`.\n\n"
        f"Changed files: {', '.join(state.current_attempt.changed_files) or 'none'}\n\n"
        "Please build and flash."
    )
    post_issue_note(state.issue_notes_url, settings.gitlab_token, summary)


def list_pending_runs(settings: Settings) -> list[dict]:
    results = []
    runs_dir = settings.runs_dir
    if not runs_dir.exists():
        return results
    for run_dir in sorted(runs_dir.glob("*/"), reverse=True):
        state_path = run_dir / "state.json"
        if not state_path.exists():
            continue
        try:
            state = BSPAgentState.load(run_dir)
        except Exception:
            continue
        if state.stage != "human_review":
            continue
        attempt = state.current_attempt
        issue_no = None
        if state.issue_notes_url:
            match = re.search(r"/issues/(\d+)/", state.issue_notes_url)
            issue_no = match.group(1) if match else None
        results.append(
            {
                "run_id": state.run_id,
                "run_dir": state.run_dir,
                "issue_no": issue_no,
                "changed_files": attempt.changed_files,
                "code_review": attempt.code_review_decision,
                "issue_first_line": (state.issue or "").splitlines()[0][:80],
            }
        )
    return results


def continue_run(run_dir: str | Path, settings: Settings) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    if state.stage in {
        "classify_error",
        "select_skills",
        "load_skill",
        "inspect_repo",
        "propose_patch",
        "validate_patch",
        "code_review",
    }:
        _run_repair_pipeline(state, settings)
        return state
    if state.stage == "report":
        generate_report(Path(state.run_dir))
        return BSPAgentState.load(run_dir)
    raise RuntimeError(f"Run is not waiting for continue: {state.stage}")


def register_target(
    run_dir: str | Path,
    ssh_target: str,
    git_ref: str,
    port: int = 22,
    build_label: str | None = None,
) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    attempt = state.current_attempt
    if attempt.human_review_status != "approved":
        raise RuntimeError("Target can only be registered after patch approval.")
    user, host = _parse_ssh_target(ssh_target)
    attempt.target = TargetInfo(
        ssh_target=ssh_target,
        host=host,
        user=user,
        port=port,
        git_ref=git_ref,
        build_label=build_label,
    )
    write_json(_attempt_dir(state) / "target.json", attempt.target.model_dump())
    state.stage = "target_ready"
    state.touch()
    state.save()
    return state


def run_validation(
    run_dir: str | Path,
    script: str,
    timeout_sec: int,
    settings: Settings,
) -> BSPAgentState:
    state = BSPAgentState.load(run_dir)
    attempt = state.current_attempt
    if not attempt.target:
        raise RuntimeError("Register a target before running validation.")
    index = len(attempt.validation_runs) + 1
    validation_path = validation_run_dir(_attempt_dir(state), index, script)
    validation_id = validation_path.name
    remote_dir = f"/tmp/bsp-agent/{state.run_id}/{attempt.attempt_no:03d}/{validation_id}"
    info = ValidationRunInfo(
        validation_id=validation_id,
        script=script,
        target_ssh=attempt.target.ssh_target,
        status="running",
        started_at=now_iso(),
    )
    attempt.validation_runs.append(info)
    state.stage = "run_tests"
    state.touch()
    state.save()

    result = run_validation_script(
        validation_dir=settings.validation_dir,
        script_name=script,
        ssh_target=attempt.target.ssh_target,
        remote_dir=remote_dir,
        output_dir=validation_path,
        port=attempt.target.port,
        timeout_sec=timeout_sec,
    )
    info.status = result["status"]  # type: ignore[assignment]
    info.returncode = int(result["returncode"])
    info.duration_sec = float(result["duration_sec"])
    info.stdout_path = str(result["stdout_path"])
    info.stderr_path = str(result["stderr_path"])
    info.completed_at = now_iso()
    write_json(validation_path / "result.json", info.model_dump())

    if info.status == "success":
        state.stage = "report"
        generate_report(Path(state.run_dir))
    elif len(state.attempts) >= state.max_loops:
        state.stage = "report"
        generate_report(Path(state.run_dir))
    else:
        _analyze_validation_failure(state, validation_path)
        state.new_attempt()
        state.stage = "classify_error"
        _run_repair_pipeline(state, settings)
    state.touch()
    state.save()
    return state


def show_diff(run_dir: str | Path) -> None:
    state = BSPAgentState.load(run_dir)
    attempt = state.current_attempt
    patch = _attempt_dir(state) / "patch.md"
    if patch.exists():
        console.print("[bold]Changed Files[/bold]")
        for file_name in attempt.changed_files:
            console.print(f"- {file_name}")
        console.print("[bold]Diff[/bold]")
        try:
            diff_text = extract_diff_from_patch_md(patch.read_text(encoding="utf-8"))
            console.print(Syntax(diff_text, "diff", line_numbers=False))
        except PatchError:
            console.print(Markdown(patch.read_text(encoding="utf-8")))
        code_review = _attempt_dir(state) / "code_review.md"
        if code_review.exists():
            console.print(Markdown(code_review.read_text(encoding="utf-8")))
    else:
        no_patch = _attempt_dir(state) / "no_patch.md"
        if no_patch.exists():
            console.print(Markdown(no_patch.read_text(encoding="utf-8")))
        else:
            console.print("[yellow]No diff found for current attempt.[/yellow]")


def generate_report(run_dir: str | Path) -> Path:
    state = BSPAgentState.load(run_dir)
    report_path = Path(state.run_dir) / "report.md"
    lines = [
        "# Jetson BSP Repair Report",
        "",
        "## 1. Issue Summary",
        "",
        state.issue,
        "",
        "## 2. Attempts",
        "",
    ]
    final_status = "WAITING_FOR_REVIEW"
    for attempt in state.attempts:
        lines.extend(_attempt_report(state, attempt))
        if any(run.status == "success" for run in attempt.validation_runs):
            final_status = "PASS"
        elif len(state.attempts) >= state.max_loops and attempt.validation_runs:
            final_status = "FAIL_AFTER_MAX_RETRIES"
        elif attempt.patch_status in {"no_patch", "failed"}:
            final_status = "PATCH_GENERATION_FAILED"
    lines.extend(["", "## 3. Final Status", "", final_status, ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    state.report_path = str(report_path)
    state.stage = "done" if final_status == "PASS" else state.stage
    state.touch()
    state.save()
    return report_path


def _run_repair_pipeline(state: BSPAgentState, settings: Settings) -> None:
    from agent.graph import run_repair_graph

    run_repair_graph(state, settings)


def _prepare_managed_branch(repo: Path, run_id: str, settings: Settings) -> str | None:
    if not settings.auto_push_enabled:
        return None
    original_branch = current_branch(repo)
    base_branch = settings.bsp_base_branch or original_branch
    if settings.bsp_base_branch:
        checkout_branch(repo, settings.bsp_base_branch, create=False)
    pull_ff_only(repo, settings.git_remote, settings.bsp_base_branch)
    checkout_branch(repo, f"bsp-agent/{run_id}", create=True)
    return base_branch


def _cleanup_managed_branch(state: BSPAgentState, settings: Settings) -> None:
    if not settings.auto_push_enabled:
        return
    if any(attempt.publish_status == "pushed" for attempt in state.attempts):
        return
    branch = f"bsp-agent/{state.run_id}"
    base_branch = state.managed_base_branch or settings.bsp_base_branch
    if not base_branch:
        return
    try:
        if branch_exists(state.repo_path, branch):
            checkout_branch(state.repo_path, base_branch, create=False)
            delete_branch(state.repo_path, branch)
    except Exception:  # noqa: BLE001
        console.print(f"[yellow]Warning: failed to clean up managed branch {branch}.[/yellow]")


def _propose_patch(
    state: BSPAgentState,
    attempt: RepairAttempt,
    skill_text: str,
    repo_inspection: str,
    settings: Settings,
    rag_context: str = "",
) -> tuple[str, str | None]:
    system_prompt = (
        "You are a conservative Jetson BSP patch generator. Output search/replace "
        "edit blocks only, or NO_PATCH followed by a short reason. Do not output "
        "unified diffs."
    )
    user_prompt = (
        f"Issue:\n{state.issue}\n\n"
        f"Bug type: {attempt.bug_type}\n"
        f"Error signatures: {attempt.error_signatures}\n"
        f"Suspected areas: {attempt.suspected_areas}\n\n"
        f"Retry context (previous attempts in this run):\n{build_retry_context(state)[:8000]}\n\n"
        f"Previous review feedback:\n{_review_feedback_context(state)}\n\n"
        f"BSP Knowledge Base (RAG retrieval):\n{rag_context[:8000]}\n\n"
        f"Retrieved skills:\n{skill_text[:20000]}\n\n"
        f"Repo inspection:\n{repo_inspection[:40000]}\n"
        "\nEdit block format:\n"
        "FILE: <repo-relative path>\n"
        "REPLACE_ALL: <true|false>  # optional, default false\n"
        "<<<<<<< SEARCH\n"
        "<exact current text>\n"
        "=======\n"
        "<replacement text>\n"
        ">>>>>>> REPLACE\n"
        "\nRules:\n"
        "- Output only edit blocks in the exact format above or NO_PATCH <reason>.\n"
        "- Include enough surrounding context in SEARCH for a unique exact match.\n"
        "- Use one block per distinct change.\n"
        "- For the same change across several near-identical blocks, use REPLACE_ALL: true.\n"
        "- Preserve whitespace and indentation exactly from the inspected source excerpts.\n"
        "- Prefer minimal single-line or small replacements instead of replacing a whole DTS node.\n"
        "- Do not add explanatory comments to source files unless the existing file style requires it.\n"
        "- Do not invent files; FILE must point to an existing repo-relative path.\n"
        "- Do not invent clocks, regulators, GPIOs, or board facts not present in the inspected source.\n"
        "- Do not repeat a patch that was rejected by human review.\n"
        "- Use human feedback as higher-priority evidence than your previous patch.\n"
        "- Use validation failures as evidence about runtime behavior on the flashed target.\n"
        "- If the retry context conflicts with skill instructions, explain by returning NO_PATCH.\n"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    write_text(
        _attempt_dir(state) / "proposed_patch_prompt.md",
        _proposed_patch_prompt_markdown(attempt, system_prompt, user_prompt),
    )
    try:
        response = chat_completion(
            LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model),
            messages,
            timeout_sec=60,
            name="patch_agent",
        )
    except LLMError as exc:
        return "NO_PATCH", f"LLM unavailable or returned an invalid response: {exc}"
    write_text(_attempt_dir(state) / "proposed_patch_raw.md", response)
    if response.strip() == "NO_PATCH" or response.lstrip().startswith("NO_PATCH"):
        reason = response.strip()[len("NO_PATCH") :].strip(" :-\n") or "No safe patch was proposed."
        return "NO_PATCH", reason
    return response, None


def _proposed_patch_prompt_markdown(attempt: RepairAttempt, system_prompt: str, user_prompt: str) -> str:
    return (
        "# Proposed Patch Prompt\n\n"
        f"Attempt: `{attempt.attempt_no:03d}`\n\n"
        "## System Message\n\n"
        f"{system_prompt}\n\n"
        "## User Message\n\n"
        f"{user_prompt}\n"
    )


def _input_markdown(issue: str, logs: list[str]) -> str:
    lines = ["# Input", "", "## Issue", "", issue, "", "## Logs", ""]
    lines.extend(f"- `{path}`" for path in logs)
    return "\n".join(lines) + "\n"


def _review_feedback_context(state: BSPAgentState) -> str:
    rejected = [
        attempt
        for attempt in state.attempts[:-1]
        if attempt.human_review_status == "rejected" and attempt.human_feedback
    ]
    if not rejected:
        return "(none)"
    lines: list[str] = []
    for attempt in rejected:
        lines.append(f"- Attempt {attempt.attempt_no:03d}: {attempt.human_feedback}")
    return "\n".join(lines)


def _attempt_dir(state: BSPAgentState) -> Path:
    return attempt_dir(state.run_dir, state.current_attempt.attempt_no)


def _keywords_for_attempt(state: BSPAgentState, attempt: RepairAttempt) -> list[str]:
    keywords = _keyword_candidates_from_text(state.issue)
    keywords.extend(_keyword_candidates_from_text(" ".join(attempt.error_signatures)))
    keywords.extend(attempt.suspected_areas)
    if attempt.bug_type:
        keywords.append(attempt.bug_type)
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        clean = " ".join(str(keyword).split())
        if not clean or "\n" in clean or len(clean) > 80:
            continue
        if clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def _keyword_candidates_from_text(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_-]{2,}|-\d+", text)
    useful: list[str] = []
    stop = {
        "after",
        "with",
        "and",
        "the",
        "custom",
        "flashing",
        "fails",
        "failed",
        "failure",
        "missing",
    }
    for token in tokens:
        lowered = token.lower()
        if lowered in stop:
            continue
        useful.append(token)
    return useful


def _repo_inspection_text(repo_path: str, candidates: list[str]) -> str:
    lines = ["# Repo Inspection", "", "## Candidate Files", ""]
    if not candidates:
        lines.append("No candidate files found.")
        return "\n".join(lines) + "\n"
    for file_name in candidates:
        lines.append(f"- `{file_name}`")
    lines.extend(["", "## File Excerpts", ""])
    for file_name in candidates[:8]:
        lines.append(f"### `{file_name}`")
        try:
            content = read_text_file(repo_path, file_name, max_chars=4000)
        except Exception as exc:  # noqa: BLE001
            content = f"(Could not read file: {exc})"
        lines.append("```")
        lines.append(content)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _write_no_patch(state: BSPAgentState, reason: str) -> None:
    write_text(
        _attempt_dir(state) / "no_patch.md",
        "# No Patch\n\n"
        "## Reason\n\n"
        f"{reason}\n\n"
        "## Requested Information\n\n"
        "- Provide more complete logs or a source hint for the board-specific BSP files.\n",
    )


def _patch_markdown(attempt: RepairAttempt, diff_text: str) -> str:
    """Render the canonical patch.md artifact: attempt number, changed files,
    and one fenced diff block containing the full unified diff."""
    files = "\n".join(f"- `{file}`" for file in attempt.changed_files) or "- (none)"
    if not diff_text.endswith("\n"):
        diff_text += "\n"
    return (
        "# Patch\n\n"
        f"Attempt: `{attempt.attempt_no:03d}`\n\n"
        "## Changed Files\n\n"
        f"{files}\n\n"
        "## Diff\n\n"
        "```diff\n"
        f"{diff_text}"
        "```\n"
    )


def _publish_commit_message(state: BSPAgentState, attempt: RepairAttempt) -> str:
    issue = " ".join(state.issue.split())
    if len(issue) > 200:
        issue = f"{issue[:197]}..."
    files = attempt.changed_files or ["(none)"]
    changed_files = "\n".join(f"- {file_name}" for file_name in files)
    return (
        f"BSP agent patch (run {state.run_id}, attempt {attempt.attempt_no:03d})\n\n"
        f"Issue: {issue}\n"
        "Changed files:\n"
        f"{changed_files}\n"
    )


def _write_publish_artifact(state: BSPAgentState, attempt: RepairAttempt, remote: str) -> None:
    write_json(
        _attempt_dir(state) / "publish.json",
        {
            "branch": attempt.published_branch,
            "commit": attempt.published_commit,
            "remote": remote,
            "status": attempt.publish_status,
            "error": attempt.publish_error,
            "changed_files": attempt.changed_files,
        },
    )


def _parse_ssh_target(ssh_target: str) -> tuple[str | None, str]:
    if "@" in ssh_target:
        user, host = ssh_target.split("@", 1)
        return user, host
    return None, ssh_target


def _analyze_validation_failure(state: BSPAgentState, validation_path: Path) -> None:
    stdout = (validation_path / "stdout.txt").read_text(errors="replace", encoding="utf-8")
    stderr = (validation_path / "stderr.txt").read_text(errors="replace", encoding="utf-8")
    text = (
        "# Validation Failure Analysis\n\n"
        "The validation script returned a non-zero exit code. The next repair attempt should "
        "reinspect the same BSP source repo using this validation output.\n\n"
        "## stdout\n\n"
        "```text\n"
        f"{stdout[:8000]}\n"
        "```\n\n"
        "## stderr\n\n"
        "```text\n"
        f"{stderr[:8000]}\n"
        "```\n"
    )
    state.current_attempt.analysis_result = text
    write_text(_attempt_dir(state) / "analyze_result.md", text)


def _attempt_report(state: BSPAgentState, attempt: RepairAttempt) -> list[str]:
    attempt_path = Path(state.run_dir) / "attempts" / f"{attempt.attempt_no:03d}"
    lines = [
        f"### Attempt {attempt.attempt_no:03d}",
        "",
        f"- Patch status: `{attempt.patch_status}`",
        f"- Review status: `{attempt.human_review_status}`",
        f"- Bug type: `{attempt.bug_type}`",
        f"- Selected skills: `{', '.join(attempt.selected_skills) or 'none'}`",
    ]
    if attempt.code_review_decision:
        lines.append(
            f"- Code review: `{attempt.code_review_decision}` "
            f"(confidence `{attempt.code_review_confidence}`)"
        )
    if attempt.target:
        lines.append(f"- Target: `{attempt.target.ssh_target}`")
        lines.append(f"- Git ref evidence: `{attempt.target.git_ref}`")
    for validation in attempt.validation_runs:
        lines.append(
            f"- Validation `{validation.validation_id}`: `{validation.status}` "
            f"exit `{validation.returncode}` script `{validation.script}`"
        )
    for name in ["patch.md", "code_review.md", "no_patch.md", "analyze_result.md"]:
        path = attempt_path / name
        if path.exists():
            lines.append(f"- Artifact: `{path}`")
    lines.append("")
    return lines
