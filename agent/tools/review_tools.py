from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.config import Settings
from agent.state import BSPAgentState, RepairAttempt
from agent.tools.artifact_tools import attempt_dir, write_json, write_text
from agent.tools.llm_tools import LLMConfig, LLMError, chat_completion, strip_json_fence
from agent.tools.retry_tools import build_retry_context


_POLICY_PATH = Path(__file__).resolve().parent.parent / "prompts" / "code_review_policy.md"
_ALLOWED_DECISIONS = {"pass", "reject", "needs_human"}


def run_code_review(
    state: BSPAgentState,
    attempt: RepairAttempt,
    diff_text: str,
    repo_inspection: str,
    settings: Settings,
) -> dict[str, Any]:
    """Run the Code Review Agent on a validated, not-yet-applied diff.

    The reviewer has its own context (issue, selected skills, repo inspection,
    diff, policy, retry context) and never sees the Patch Agent prompt. Any
    LLM failure or invalid JSON falls back to needs_human so a broken reviewer
    can never auto-accept or silently burn retries.
    """
    messages = _build_messages(state, attempt, diff_text, repo_inspection)
    raw: str | None = None
    try:
        raw = chat_completion(
            LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model),
            messages,
            timeout_sec=settings.llm_timeout_sec,
            name="code_review_agent",
        )
        review = _parse_review(raw)
    except LLMError as exc:
        review = _fallback_review(f"Code Review Agent LLM unavailable: {exc}")
    except ReviewParseError as exc:
        review = _fallback_review(f"Code Review Agent returned invalid output: {exc}")

    review["raw_response"] = raw
    _record_review(state, attempt, review)
    return review


def load_review_policy() -> str:
    return _POLICY_PATH.read_text(encoding="utf-8")


class ReviewParseError(RuntimeError):
    pass


def _build_messages(
    state: BSPAgentState,
    attempt: RepairAttempt,
    diff_text: str,
    repo_inspection: str,
) -> list[dict[str, str]]:
    system = (
        "You are an independent Jetson BSP code reviewer. You did not write the patch. "
        "Review it strictly against the policy and the provided evidence only. "
        "Return strict JSON only, no prose, with this schema:\n"
        "{\n"
        '  "decision": "pass" | "reject" | "needs_human",\n'
        '  "confidence": 0.0,\n'
        '  "findings": ["short factual finding"],\n'
        '  "required_changes": ["change the Patch Agent must make"]\n'
        "}\n\n"
        "Policy:\n"
        f"{load_review_policy()}"
    )
    user = (
        f"Issue:\n{state.issue}\n\n"
        f"Selected skills: {', '.join(attempt.selected_skills) or 'none'}\n\n"
        f"Retry context (previous attempts in this run):\n{build_retry_context(state)[:8000]}\n\n"
        f"Repo inspection evidence:\n{repo_inspection[:20000]}\n\n"
        "Proposed patch (validated with git apply --check, not applied yet):\n"
        "```diff\n"
        f"{diff_text}"
        "```\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_review(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        raise ReviewParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ReviewParseError("JSON is not an object")
    decision = str(parsed.get("decision", "")).strip().lower()
    if decision not in _ALLOWED_DECISIONS:
        raise ReviewParseError(f"decision must be one of {sorted(_ALLOWED_DECISIONS)}")
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError) as exc:
        raise ReviewParseError("confidence is not a number") from exc
    confidence = min(max(confidence, 0.0), 1.0)
    return {
        "decision": decision,
        "confidence": confidence,
        "findings": _string_list(parsed.get("findings")),
        "required_changes": _string_list(parsed.get("required_changes")),
    }


def _fallback_review(reason: str) -> dict[str, Any]:
    return {
        "decision": "needs_human",
        "confidence": 0.0,
        "findings": [reason],
        "required_changes": [],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _record_review(state: BSPAgentState, attempt: RepairAttempt, review: dict[str, Any]) -> None:
    attempt.code_review_decision = review["decision"]
    attempt.code_review_confidence = review["confidence"]
    attempt.code_review_findings = list(review["findings"])
    attempt.code_review_required_changes = list(review["required_changes"])
    path = attempt_dir(state.run_dir, attempt.attempt_no)
    write_json(path / "review_agent_raw.json", review)
    write_text(path / "code_review.md", _render_review_md(attempt, review))


def _render_review_md(attempt: RepairAttempt, review: dict[str, Any]) -> str:
    findings = "\n".join(f"- {item}" for item in review["findings"]) or "- (none)"
    required = "\n".join(f"- {item}" for item in review["required_changes"]) or "- (none)"
    return (
        "# Code Review\n\n"
        f"Attempt: `{attempt.attempt_no:03d}`\n\n"
        f"- Decision: `{review['decision']}`\n"
        f"- Confidence: `{review['confidence']:.2f}`\n\n"
        "## Findings\n\n"
        f"{findings}\n\n"
        "## Required Changes\n\n"
        f"{required}\n"
    )
