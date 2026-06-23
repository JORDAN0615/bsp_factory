import json
from pathlib import Path

from agent.config import Settings
from agent.state import BSPAgentState
from agent.tools.llm_tools import LLMError
from agent.tools.review_tools import run_code_review


def make_state(tmp_path: Path) -> BSPAgentState:
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    state = BSPAgentState(
        run_id="run-1",
        repo_path=str(tmp_path / "repo"),
        run_dir=str(run_dir),
        issue="camera probe failed",
    )
    state.new_attempt()
    return state


def make_settings() -> Settings:
    return Settings(LLM_BASE_URL="http://127.0.0.1:9/v1", LLM_API_KEY="EMPTY", LLM_MODEL="test")


DIFF = """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay";
"""


def test_review_pass_records_state_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    state = make_state(tmp_path)
    attempt = state.current_attempt
    response = json.dumps(
        {
            "decision": "pass",
            "confidence": 0.92,
            "findings": ["minimal status flip supported by inspection"],
            "required_changes": [],
        }
    )
    monkeypatch.setattr(
        "agent.tools.review_tools.chat_completion", lambda *a, **k: response
    )

    review = run_code_review(state, attempt, DIFF, "# Repo Inspection", make_settings())

    assert review["decision"] == "pass"
    assert attempt.code_review_decision == "pass"
    assert attempt.code_review_confidence == 0.92
    attempt_dir = Path(state.run_dir) / "attempts" / "001"
    raw = json.loads((attempt_dir / "review_agent_raw.json").read_text(encoding="utf-8"))
    assert raw["decision"] == "pass"
    assert raw["raw_response"] == response
    rendered = (attempt_dir / "code_review.md").read_text(encoding="utf-8")
    assert "Decision: `pass`" in rendered
    assert "minimal status flip" in rendered


def test_review_invalid_json_falls_back_to_needs_human(tmp_path: Path, monkeypatch) -> None:
    state = make_state(tmp_path)
    attempt = state.current_attempt
    monkeypatch.setattr(
        "agent.tools.review_tools.chat_completion", lambda *a, **k: "not json at all"
    )

    review = run_code_review(state, attempt, DIFF, "", make_settings())

    assert review["decision"] == "needs_human"
    assert attempt.code_review_decision == "needs_human"


def test_review_invalid_decision_falls_back_to_needs_human(tmp_path: Path, monkeypatch) -> None:
    state = make_state(tmp_path)
    attempt = state.current_attempt
    monkeypatch.setattr(
        "agent.tools.review_tools.chat_completion",
        lambda *a, **k: '{"decision": "maybe", "confidence": 0.5}',
    )

    review = run_code_review(state, attempt, DIFF, "", make_settings())

    assert review["decision"] == "needs_human"


def test_review_llm_error_falls_back_to_needs_human(tmp_path: Path, monkeypatch) -> None:
    state = make_state(tmp_path)
    attempt = state.current_attempt

    def boom(*args, **kwargs):
        raise LLMError("connection refused")

    monkeypatch.setattr("agent.tools.review_tools.chat_completion", boom)

    review = run_code_review(state, attempt, DIFF, "", make_settings())

    assert review["decision"] == "needs_human"
    assert any("connection refused" in finding for finding in review["findings"])


def test_review_confidence_is_clamped(tmp_path: Path, monkeypatch) -> None:
    state = make_state(tmp_path)
    attempt = state.current_attempt
    monkeypatch.setattr(
        "agent.tools.review_tools.chat_completion",
        lambda *a, **k: '{"decision": "pass", "confidence": 7.5}',
    )

    review = run_code_review(state, attempt, DIFF, "", make_settings())

    assert review["confidence"] == 1.0


def test_reviewer_context_is_independent_of_patch_prompt(tmp_path: Path, monkeypatch) -> None:
    state = make_state(tmp_path)
    attempt = state.current_attempt
    captured: dict = {}

    def capture(*args, **kwargs):
        captured["messages"] = args[1] if len(args) > 1 else kwargs["messages"]
        return '{"decision": "pass", "confidence": 0.9}'

    monkeypatch.setattr("agent.tools.review_tools.chat_completion", capture)

    run_code_review(state, attempt, DIFF, "# Repo Inspection evidence", make_settings())

    system = captured["messages"][0]["content"]
    user = captured["messages"][1]["content"]
    assert "code reviewer" in system
    assert "Reject when" in system  # policy is embedded
    assert "Proposed patch" in user
    assert '+status = "okay";' in user
    # The reviewer must not receive the Patch Agent prompt.
    assert "conservative Jetson BSP patch generator" not in system
    assert "conservative Jetson BSP patch generator" not in user
