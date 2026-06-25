from __future__ import annotations

from pathlib import Path
import sys

import typer
from rich.console import Console

from agent.config import get_settings
from agent.nodes.workflow import (
    approve_run,
    continue_run,
    create_run,
    generate_report,
    register_target,
    reject_run,
    run_validation,
    show_diff,
)
from agent.state import BSPAgentState
from agent.tools.git_tools import GitError
from agent.tools.patch_tools import PatchError
from agent.tools.path_tools import SafetyError
from agent.tools.test_tools import ValidationError


app = typer.Typer(help="Controlled Jetson BSP repair and validation agent.")
console = Console()


def fail(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(code=1)


@app.command("init-run")
def init_run(
    repo: Path = typer.Option(..., exists=True, file_okay=False, help="BSP source repo."),
    issue: str = typer.Option(..., help="Issue summary."),
    log: list[Path] = typer.Option(None, exists=True, dir_okay=False, help="Input log file."),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        help="Prompt for approve/reject immediately when human review is reached.",
    ),
) -> None:
    try:
        state = create_run(repo=repo, issue=issue, logs=log or [], settings=get_settings())
    except (GitError, SafetyError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[green]Created run:[/green] {state.run_dir}")
    console.print(f"[cyan]Stage:[/cyan] {state.stage}")
    if state.stage == "human_review":
        console.print()
        show_diff(state.run_dir)
        console.print()
        if interactive and sys.stdin.isatty():
            _review_prompt(Path(state.run_dir))
        else:
            _print_review_commands(state.run_dir)
    elif state.stage == "report":
        console.print("[yellow]No reviewable patch after retries; see report.md.[/yellow]")


@app.command("show-diff")
def show_diff_cmd(run: Path = typer.Option(..., exists=True, file_okay=False)) -> None:
    try:
        show_diff(run)
    except (RuntimeError, ValueError) as exc:
        fail(str(exc))


@app.command("continue")
def continue_cmd(run: Path = typer.Option(..., exists=True, file_okay=False)) -> None:
    try:
        state = continue_run(run, get_settings())
    except (GitError, PatchError, SafetyError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[green]Continued run.[/green] Stage: {state.stage}")


@app.command("approve")
def approve(run: Path = typer.Option(..., exists=True, file_okay=False)) -> None:
    try:
        state = approve_run(run, get_settings())
    except (RuntimeError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[green]Approved attempt {state.current_attempt.attempt_no:03d}.[/green]")
    _print_publish_handoff(state)


@app.command("review")
def review(run: Path = typer.Option(..., exists=True, file_okay=False)) -> None:
    try:
        show_diff(run)
        _review_prompt(run)
    except (GitError, PatchError, RuntimeError, ValueError) as exc:
        fail(str(exc))


@app.command("reject")
def reject(
    run: Path = typer.Option(..., exists=True, file_okay=False),
    feedback: str = typer.Option(..., help="Human review feedback."),
) -> None:
    try:
        state = reject_run(run, feedback, get_settings())
    except (GitError, PatchError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[yellow]Rejected. New attempt: {state.current_attempt.attempt_no:03d}[/yellow]")


@app.command("register-target")
def register_target_cmd(
    run: Path = typer.Option(..., exists=True, file_okay=False),
    ssh_target: str = typer.Option(..., help="SSH target, for example nvidia@192.168.1.50."),
    git_ref: str = typer.Option(..., help="Human-declared Git ref flashed on target."),
    port: int = typer.Option(22),
    build_label: str | None = typer.Option(None),
) -> None:
    try:
        state = register_target(run, ssh_target, git_ref, port, build_label)
    except (RuntimeError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[green]Registered target for attempt {state.current_attempt.attempt_no:03d}.[/green]")


@app.command("run-tests")
def run_tests(
    run: Path = typer.Option(..., exists=True, file_okay=False),
    script: str = typer.Option(..., help="Script name under tests/validation/."),
    timeout_sec: int = typer.Option(300),
) -> None:
    try:
        state = run_validation(run, script, timeout_sec=timeout_sec, settings=get_settings())
    except (SafetyError, ValidationError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    result = state.current_attempt.validation_runs[-1]
    color = "green" if result.status == "success" else "red"
    console.print(f"[{color}]Validation {result.status}: {script} exit={result.returncode}[/{color}]")


@app.command("report")
def report(run: Path = typer.Option(..., exists=True, file_okay=False)) -> None:
    try:
        path = generate_report(run)
    except (RuntimeError, ValueError) as exc:
        fail(str(exc))
    console.print(f"[green]Report written:[/green] {path}")


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0"),
    port: int = typer.Option(8080),
) -> None:
    import uvicorn

    uvicorn.run("agent.server:app", host=host, port=port)


@app.command("unlock")
def unlock() -> None:
    from agent import run_lock

    run_lock.release_active(get_settings().runs_dir)
    console.print("Cleared the active-run marker.")


def _review_prompt(run: Path) -> None:
    while True:
        choice = typer.prompt("Approve patch? [a=approve, r=reject, q=quit]").strip().lower()
        if choice in {"a", "approve"}:
            state = approve_run(run, get_settings())
            console.print(f"[green]Approved attempt {state.current_attempt.attempt_no:03d}.[/green]")
            _print_publish_handoff(state)
            return
        if choice in {"r", "reject"}:
            feedback = typer.prompt("Reject feedback")
            state = reject_run(run, feedback, get_settings())
            console.print(
                f"[yellow]Rejected. Current attempt: {state.current_attempt.attempt_no:03d}[/yellow]"
            )
            if state.stage == "human_review":
                console.print()
                show_diff(state.run_dir)
                console.print()
                continue
            if state.stage == "report":
                console.print("[yellow]Reached report stage after rejection.[/yellow]")
                return
            console.print(f"[yellow]Stage after reject: {state.stage}[/yellow]")
            return
        console.print("[yellow]Review left pending.[/yellow]")
        _print_review_commands(str(run))
        return


def _print_review_commands(run_dir: str) -> None:
    console.print("[bold]Next:[/bold]")
    console.print(f"  .venv/bin/bsp-agent review --run {run_dir}", soft_wrap=True)
    console.print(f"  .venv/bin/bsp-agent approve --run {run_dir}", soft_wrap=True)
    console.print(
        f'  .venv/bin/bsp-agent reject --run {run_dir} --feedback "explain what to change"',
        soft_wrap=True,
    )


def _print_publish_handoff(state: BSPAgentState) -> None:
    # Auto-push disabled (or no publish ran): keep the human-owned handoff.
    if state.stage not in {"published", "publish_failed"}:
        console.print("Human should commit, push, build, and flash outside the agent.")
        return

    from agent.nodes.workflow import _publish_commit_message

    attempt = state.current_attempt
    branch = attempt.published_branch or f"bsp-agent/{state.run_id}"
    subject = _publish_commit_message(state, attempt).splitlines()[0]
    error = attempt.publish_error or "unknown error"

    # git commit stage
    console.print("[bold]git commit[/bold]")
    console.print(f'  message: "{subject}"')
    if attempt.published_commit:
        console.print(f"  [green]success[/green] {attempt.published_commit[:10]} on {branch}")
    else:
        console.print(f"  [red]failed[/red]: {error}")
        console.print(
            "[yellow]Patch is applied locally but not committed. "
            "Human must commit + push manually, then build and flash.[/yellow]"
        )
        return

    # git push stage
    console.print(f"[bold]git push[/bold] -> {branch}")
    if state.stage == "published":
        console.print("  [green]success[/green]")
        console.print("Human should build and flash.")
        return
    console.print(f"  [red]failed[/red]: {error}")
    console.print(
        "[yellow]Committed locally on the branch, but push failed. "
        "Human must push manually, then build and flash.[/yellow]"
    )


if __name__ == "__main__":
    app()
