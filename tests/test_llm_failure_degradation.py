"""ADR-0012: transient LLM failures degrade gracefully and never consume the
max_loops budget."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent import run_lock
from agent.config import Settings
from agent.graph import (
    _select_skills_with_llm,
    human_review_node,
    inspect_repo_node,
    patch_agent_node,
    route_after_patch_agent,
)
from agent.nodes.workflow import abandon_run, retry_run
from agent.state import BSPAgentState, RepairAttempt
from agent.tools.llm_tools import LLMError, transient_llm_errors

from test_workflow_smoke import make_repo, make_settings


# --- classification / settings -------------------------------------------------


def test_transient_llm_errors_includes_llm_error_and_openai_classes() -> None:
    import openai

    errors = transient_llm_errors()
    assert LLMError in errors
    assert openai.APITimeoutError in errors
    assert openai.APIConnectionError in errors
    assert openai.RateLimitError in errors
    assert openai.InternalServerError in errors


def test_settings_default_timeout_is_180() -> None:
    settings = Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=Path("runs"),
    )
    assert settings.llm_timeout_sec == 180
    assert settings.llm_max_retries == 2


def test_select_skills_passes_configured_timeout(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, LLM_TIMEOUT_SEC=180)
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(tmp_path / "runs" / "run123"),
        issue="camera failed",
    )
    captured: dict[str, object] = {}

    def fake_chat_completion(config, messages, timeout_sec, name):
        captured["timeout_sec"] = timeout_sec
        return '{"selected_skills": [], "confidence": 0.0, "reason": "x"}'

    monkeypatch.setattr("agent.graph.chat_completion", fake_chat_completion)

    _select_skills_with_llm(state, settings, {}, [])

    assert captured["timeout_sec"] == 180


# --- inspect_repo degradation --------------------------------------------------


def test_inspect_repo_falls_back_to_deterministic_on_llm_failure(
    tmp_path: Path, monkeypatch
) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, REACT_EVIDENCE_ENABLED=True)
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        issue="camera probe failed i2c -121",
    )
    attempt = state.new_attempt()
    attempt.error_signatures = ["probe failed"]
    attempt.suspected_areas = ["camera"]
    state.save()

    def fake_gather_evidence(*args, **kwargs):
        raise LLMError("timeout")

    monkeypatch.setattr("agent.tools.react_evidence.gather_evidence", fake_gather_evidence)

    result = inspect_repo_node({"state": state, "settings": settings})

    inspection = result["repo_inspection"]
    assert inspection.startswith("(ReAct evidence unavailable: timeout;")
    inspection_md = (Path(state.run_dir) / "attempts" / "001" / "repo_inspection.md").read_text(
        encoding="utf-8"
    )
    assert inspection_md.startswith("(ReAct evidence unavailable")
    # The run keeps moving: no failure_reason set here.
    assert state.failure_reason is None


def test_gather_evidence_partial_on_transient_failure(tmp_path: Path, monkeypatch) -> None:
    import openai

    from agent.tools.react_evidence import gather_evidence

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def stream(self, payload, config, stream_mode):
            yield {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "grep_repo", "args": {"pattern": "imx219"}, "id": "c1"}],
                    ),
                    ToolMessage(content="board.dts:1: imx219", name="grep_repo", tool_call_id="c1"),
                ]
            }
            raise openai.APITimeoutError(request=None)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeModel)
    monkeypatch.setattr("langchain.agents.create_agent", lambda *a, **k: FakeAgent())

    markdown = gather_evidence(repo, "camera failed", [], make_settings(tmp_path))

    assert "LLM transient failure after partial evidence" in markdown
    assert "grep_repo(pattern='imx219')" in markdown


# --- patch_agent retry ladder --------------------------------------------------


def _agentic_state(tmp_path: Path, repo: Path) -> BSPAgentState:
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="propose_patch",
        issue="camera failed",
    )
    state.new_attempt()
    state.save()
    return state


def test_patch_agent_llm_failure_escalates_without_burning_budget(
    tmp_path: Path, monkeypatch
) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, PATCH_AGENT_AGENTIC=True, LLM_FAILURE_NODE_RETRIES=1)
    staging = tmp_path / "agentic-staging"
    state = _agentic_state(tmp_path, repo)

    def fake_run_patch_agent(staging_path, *args, **kwargs):
        # Edit the staging copy, then fail — so the forensic dump is non-empty.
        (Path(staging_path) / "board.dts").write_text('status = "okay";\n', encoding="utf-8")
        raise LLMError("timeout")

    sleeps: list[int] = []
    monkeypatch.setattr("agent.graph.tempfile.mkdtemp", lambda prefix: str(staging))
    monkeypatch.setattr("agent.graph.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("agent.tools.patch_agent.run_patch_agent", fake_run_patch_agent)

    result = patch_agent_node(
        {"state": state, "settings": settings, "skill_text": "", "repo_inspection": ""}
    )

    # Escalates to human_review in llm_failure mode.
    assert route_after_patch_agent(result) == "human_review"
    assert state.failure_reason is not None
    assert "Patch Agent LLM unavailable" in state.failure_reason
    # Budget is untouched: no new attempt, patch_status unchanged.
    assert len(state.attempts) == 1
    assert state.current_attempt.patch_status == "not_generated"
    # rounds = 1 + 1 retry -> one sleep between the two rounds.
    assert sleeps == [settings.llm_failure_retry_delay_sec]
    # Forensic dumps of the discarded partial edits.
    debug_dir = Path(state.run_dir) / "attempts" / "001" / "debug"
    assert (debug_dir / "partial_patch_round1.diff").exists()
    assert (debug_dir / "partial_patch_round2.diff").exists()
    # The real working tree is untouched.
    assert (repo / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'
    assert not staging.exists()


def test_patch_agent_recovers_on_second_round(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    settings = make_settings(tmp_path, PATCH_AGENT_AGENTIC=True, LLM_FAILURE_NODE_RETRIES=1)
    staging = tmp_path / "agentic-staging"
    state = _agentic_state(tmp_path, repo)
    calls = {"n": 0}

    def fake_run_patch_agent(staging_path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("timeout")
        (Path(staging_path) / "board.dts").write_text('status = "okay";\n', encoding="utf-8")

    sleeps: list[int] = []
    monkeypatch.setattr("agent.graph.tempfile.mkdtemp", lambda prefix: str(staging))
    monkeypatch.setattr("agent.graph.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("agent.tools.patch_agent.run_patch_agent", fake_run_patch_agent)

    result = patch_agent_node(
        {"state": state, "settings": settings, "skill_text": "", "repo_inspection": ""}
    )

    assert state.failure_reason is None
    assert result["patch_format"] == "diff"
    assert '+status = "okay";' in result["diff_text"]
    assert route_after_patch_agent(result) == "validate_patch"
    assert sleeps == [settings.llm_failure_retry_delay_sec]
    assert not staging.exists()


# --- human_review llm_failure mode ---------------------------------------------


def _llm_failure_state(tmp_path: Path) -> BSPAgentState:
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="human_review",
        issue="camera failed",
        failure_reason="Patch Agent LLM unavailable after 2 round(s): timeout",
    )
    state.new_attempt()
    state.save()
    return state


def test_human_review_llm_failure_payload_and_no_human_directed(
    tmp_path: Path, monkeypatch
) -> None:
    state = _llm_failure_state(tmp_path)
    captured: dict[str, object] = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"action": "retry"}

    monkeypatch.setattr("agent.graph.interrupt", fake_interrupt)

    human_review_node({"state": state})

    assert captured["mode"] == "llm_failure"
    assert "timeout" in captured["failure_reason"]
    assert state.human_directed is False


def test_human_review_retry_clears_failure_and_preserves_budget(
    tmp_path: Path, monkeypatch
) -> None:
    state = _llm_failure_state(tmp_path)
    monkeypatch.setattr("agent.graph.interrupt", lambda payload: {"action": "retry"})

    result = human_review_node({"state": state})

    assert result["review_route"] == "classify_error"
    assert state.failure_reason is None
    assert state.stage == "classify_error"
    assert len(state.attempts) == 1
    assert state.human_directed is False


def test_human_review_approve_invalid_in_llm_failure_mode(tmp_path: Path, monkeypatch) -> None:
    state = _llm_failure_state(tmp_path)
    monkeypatch.setattr("agent.graph.interrupt", lambda payload: {"action": "approve"})

    with pytest.raises(RuntimeError, match="paused on an LLM failure"):
        human_review_node({"state": state})


def test_human_review_reject_invalid_in_llm_failure_mode(tmp_path: Path, monkeypatch) -> None:
    state = _llm_failure_state(tmp_path)
    monkeypatch.setattr("agent.graph.interrupt", lambda payload: {"action": "reject"})

    with pytest.raises(RuntimeError, match="paused on an LLM failure"):
        human_review_node({"state": state})


def test_human_review_retry_invalid_in_patch_review_mode(tmp_path: Path, monkeypatch) -> None:
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(tmp_path / "runs" / "run123"),
        stage="human_review",
        issue="camera failed",
    )
    attempt = state.new_attempt()
    attempt.patch_status = "generated"
    state.save()
    monkeypatch.setattr("agent.graph.interrupt", lambda payload: {"action": "retry"})

    with pytest.raises(RuntimeError, match="only valid for an LLM-failure pause"):
        human_review_node({"state": state})


# --- abandon / retry_run guards ------------------------------------------------


def test_abandon_run_accepts_llm_failure_pause(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    run_dir = tmp_path / "runs" / "run123"
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        stage="human_review",
        issue="camera failed",
        failure_reason="Patch Agent LLM unavailable after 2 round(s): timeout",
        attempts=[RepairAttempt(attempt_no=1)],
    )
    state.save()
    assert run_lock.acquire_active(settings.runs_dir)

    monkeypatch.setattr("agent.nodes.workflow.run_git", lambda repo_path, args: None)
    monkeypatch.setattr("agent.nodes.workflow._cleanup_managed_branch", lambda state, settings: None)

    result = abandon_run(run_dir, settings)

    assert result.stage == "report"
    assert not run_lock.is_active(settings.runs_dir)


def test_retry_run_requires_llm_failure_pause(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    run_dir = tmp_path / "runs" / "run123"
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        stage="human_review",
        issue="camera failed",
        attempts=[RepairAttempt(attempt_no=1, patch_status="generated")],
    )
    state.save()

    with pytest.raises(RuntimeError, match="not paused on an LLM failure"):
        retry_run(run_dir, settings)
