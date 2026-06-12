from __future__ import annotations

import sqlite3
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent.config import Settings
from agent.state import BSPAgentState
from agent.tools.artifact_tools import write_json, write_text
from agent.tools.llm_tools import LLMConfig, LLMError, chat_completion
from agent.tools.patch_tools import (
    PatchError,
    apply_patch,
    changed_files_from_diff,
    extract_diff_from_patch_md,
    normalize_hunk_headers,
    reverse_patch,
)
from agent.tools.repo_tools import list_candidate_files
from agent.tools.skill_tools import (
    build_skill_catalog,
    classify_with_patterns,
    load_known_patterns,
    load_selected_skills,
    select_skills,
    validate_selected_skills,
)


class RepairGraphState(TypedDict, total=False):
    state: BSPAgentState
    settings: Settings
    logs_text: list[str]
    skill_text: str
    repo_inspection: str
    diff_text: str
    no_patch_reason: str | None
    review_route: str


def build_repair_graph(checkpointer=None):
    graph = StateGraph(RepairGraphState)
    graph.add_node("classify_error", classify_error_node)
    graph.add_node("select_skills", select_skills_node)
    graph.add_node("load_skill", load_skill_node)
    graph.add_node("inspect_repo", inspect_repo_node)
    graph.add_node("propose_patch", propose_patch_node)
    graph.add_node("write_no_patch", write_no_patch_node)
    graph.add_node("apply_patch", apply_patch_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "classify_error")
    graph.add_edge("classify_error", "select_skills")
    graph.add_edge("select_skills", "load_skill")
    graph.add_edge("load_skill", "inspect_repo")
    graph.add_edge("inspect_repo", "propose_patch")
    graph.add_conditional_edges(
        "propose_patch",
        route_after_propose_patch,
        {"write_no_patch": "write_no_patch", "apply_patch": "apply_patch"},
    )
    graph.add_edge("write_no_patch", "human_review")
    graph.add_edge("apply_patch", "human_review")
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "end": END,
            "classify_error": "classify_error",
        },
    )
    return graph.compile(checkpointer=checkpointer)


def run_repair_graph(state: BSPAgentState, settings: Settings) -> BSPAgentState:
    logs_text = [Path(path).read_text(errors="replace", encoding="utf-8") for path in state.input_logs]
    with _sqlite_checkpointer(state) as checkpointer:
        result = build_repair_graph(checkpointer).invoke(
            {
                "state": state,
                "settings": settings,
                "logs_text": logs_text,
                "skill_text": "",
                "repo_inspection": "",
                "diff_text": "",
                "no_patch_reason": None,
            },
            config=_graph_config(state),
        )
    if result and "state" in result:
        return result["state"]
    return BSPAgentState.load(state.run_dir)


def resume_review_graph(
    state: BSPAgentState,
    settings: Settings,
    decision: dict[str, str],
) -> BSPAgentState:
    with _sqlite_checkpointer(state) as checkpointer:
        result = build_repair_graph(checkpointer).invoke(
            Command(resume=decision),
            config=_graph_config(state),
        )
    if result and "state" in result:
        return result["state"]
    return BSPAgentState.load(state.run_dir)


def classify_error_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    state.stage = "classify_error"
    patterns = load_known_patterns(settings.skills_dir)
    classification = classify_with_patterns(state.issue, graph_state.get("logs_text", []), patterns)
    attempt.bug_type = classification.get("bug_type")
    attempt.error_signatures = list(classification.get("error_signatures", []))
    attempt.suspected_areas = list(classification.get("suspected_areas", []))
    from agent.nodes.workflow import _attempt_dir

    write_json(_attempt_dir(state) / "error_classification.json", classification)
    _save_state(state)
    return {"state": state}


def select_skills_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    classification = {
        "selected_skills": attempt.selected_skills,
        "bug_type": attempt.bug_type,
        "error_signatures": attempt.error_signatures,
        "suspected_areas": attempt.suspected_areas,
    }
    from agent.nodes.workflow import _attempt_dir
    from agent.tools.artifact_tools import read_json

    classification_path = _attempt_dir(state) / "error_classification.json"
    if classification_path.exists():
        classification = read_json(classification_path)
    state.stage = "select_skills"
    catalog = build_skill_catalog(settings.skills_dir)
    write_json(_attempt_dir(state) / "skill_catalog.json", catalog)
    selection = _select_skills_with_llm(state, settings, classification, catalog)
    selected = validate_selected_skills(
        selection.get("selected_skills", []),
        settings.skills_dir,
        max_skills=settings.max_selected_skills,
    )
    if not selected:
        selected = select_skills(
            classification, settings.skills_dir, max_skills=settings.max_selected_skills
        )
        selection = {
            "selected_skills": selected,
            "confidence": 0.0,
            "reason": "Fell back to known_error_patterns.yaml/default skills.",
            "fallback": True,
        }
    attempt.selected_skills = selected
    write_json(_attempt_dir(state) / "skill_selection.json", selection)
    write_json(_attempt_dir(state) / "selected_skills.json", attempt.selected_skills)
    _save_state(state)
    return {"state": state}


def load_skill_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    state.stage = "load_skill"
    skill_text = ""
    if attempt.selected_skills:
        skill_text = load_selected_skills(settings.skills_dir, attempt.selected_skills)
    from agent.nodes.workflow import _attempt_dir

    write_text(_attempt_dir(state) / "retrieved_skills.md", skill_text or "(No skills selected.)\n")
    _save_state(state)
    return {"state": state, "skill_text": skill_text}


def inspect_repo_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    state.stage = "inspect_repo"
    from agent.nodes.workflow import _attempt_dir, _keywords_for_attempt, _repo_inspection_text

    keywords = _keywords_for_attempt(state, attempt)
    candidates = list_candidate_files(state.repo_path, keywords) if keywords else []
    repo_inspection = _repo_inspection_text(state.repo_path, candidates)
    write_text(_attempt_dir(state) / "repo_inspection.md", repo_inspection)
    _save_state(state)
    return {"state": state, "repo_inspection": repo_inspection}


def propose_patch_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    state.stage = "propose_patch"
    from agent.nodes.workflow import _propose_patch

    diff_text, no_patch_reason = _propose_patch(
        state,
        attempt,
        graph_state.get("skill_text", ""),
        graph_state.get("repo_inspection", ""),
        settings,
    )
    _save_state(state)
    return {"state": state, "diff_text": diff_text, "no_patch_reason": no_patch_reason}


def route_after_propose_patch(graph_state: RepairGraphState) -> Literal["write_no_patch", "apply_patch"]:
    if graph_state.get("no_patch_reason") or graph_state.get("diff_text") == "NO_PATCH":
        return "write_no_patch"
    return "apply_patch"


def write_no_patch_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    from agent.nodes.workflow import _write_no_patch

    _write_no_patch(state, graph_state.get("no_patch_reason") or "No safe patch was proposed.")
    attempt.patch_status = "no_patch"
    state.stage = "human_review"
    _save_state(state)
    return {"state": state}


def apply_patch_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    state.stage = "apply_patch"
    diff_text = graph_state.get("diff_text", "")
    from agent.nodes.workflow import _attempt_dir, _patch_markdown, _write_no_patch

    try:
        diff_text = normalize_hunk_headers(state.repo_path, diff_text)
        apply_patch(state.repo_path, diff_text)
    except PatchError as exc:
        _write_no_patch(state, f"Patch validation or apply failed: {exc}")
        attempt.patch_status = "failed"
        state.stage = "failed"
        _save_state(state)
        return {"state": state}

    attempt.changed_files = changed_files_from_diff(diff_text)
    write_text(
        _attempt_dir(state) / "patch.md",
        _patch_markdown(attempt, diff_text),
    )
    attempt.patch_status = "applied"
    state.stage = "human_review"
    _save_state(state)
    return {"state": state, "diff_text": diff_text}


def human_review_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    state.stage = "human_review"
    _save_state(state)
    from agent.nodes.workflow import _attempt_dir

    payload = {
        "type": "human_review",
        "run_id": state.run_id,
        "run_dir": state.run_dir,
        "attempt_no": attempt.attempt_no,
        "patch_status": attempt.patch_status,
        "changed_files": attempt.changed_files,
        "patch_path": str(_attempt_dir(state) / "patch.md"),
        "no_patch_path": str(_attempt_dir(state) / "no_patch.md"),
        "message": "Review the patch and resume with approve or reject.",
    }
    decision = interrupt(payload)
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == "approve":
        if attempt.patch_status == "no_patch":
            raise RuntimeError("Cannot approve a NO_PATCH attempt.")
        attempt.human_review_status = "approved"
        state.stage = "target_ready"
        from agent.nodes.workflow import _attempt_dir

        (_attempt_dir(state) / "review.md").write_text("Status: approved\n", encoding="utf-8")
        _save_state(state)
        return {"state": state, "review_route": "end"}
    if action == "reject":
        feedback = ""
        if isinstance(decision, dict):
            feedback = str(decision.get("feedback") or "")
        if attempt.patch_status == "applied":
            patch_path = _attempt_dir(state) / "patch.md"
            diff_text = extract_diff_from_patch_md(patch_path.read_text(encoding="utf-8"))
            reverse_patch(state.repo_path, diff_text)
        attempt.human_review_status = "rejected"
        attempt.human_feedback = feedback
        (_attempt_dir(state) / "review.md").write_text(
            f"Status: rejected\n\nFeedback:\n{feedback}\n", encoding="utf-8"
        )
        if len(state.attempts) >= state.max_loops:
            state.stage = "report"
            _save_state(state)
            return {"state": state, "review_route": "end"}
        state.new_attempt()
        state.stage = "classify_error"
        _save_state(state)
        return {"state": state, "review_route": "classify_error"}
    raise RuntimeError(f"Unknown human review action: {action}")


def route_after_human_review(graph_state: RepairGraphState) -> Literal["end", "classify_error"]:
    route = graph_state.get("review_route")
    if route == "classify_error":
        return "classify_error"
    return "end"


def _select_skills_with_llm(
    state: BSPAgentState,
    settings: Settings,
    classification: dict[str, object],
    catalog: list[dict[str, str]],
) -> dict[str, object]:
    messages = [
        {
            "role": "system",
            "content": (
                "You select Jetson BSP skills for a repair agent. "
                "Use only the provided skill catalog metadata. "
                "Return strict JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Given the BSP issue, logs classification, and skill catalog, choose at most "
                f"{settings.max_selected_skills} skill folders to fully load next.\n\n"
                "Return JSON schema:\n"
                "{\n"
                '  "selected_skills": ["folder-name"],\n'
                '  "confidence": 0.0,\n'
                '  "reason": "short reason"\n'
                "}\n\n"
                f"Issue:\n{state.issue}\n\n"
                f"Classification:\n{json.dumps(classification, ensure_ascii=False, indent=2)}\n\n"
                f"Skill catalog metadata:\n{json.dumps(catalog, ensure_ascii=False, indent=2)}\n"
            ),
        },
    ]
    try:
        raw = chat_completion(
            LLMConfig(settings.llm_base_url, settings.llm_api_key, settings.llm_model),
            messages,
            timeout_sec=60,
        )
    except LLMError as exc:
        return {
            "selected_skills": [],
            "confidence": 0.0,
            "reason": f"LLM skill selection unavailable: {exc}",
            "fallback": True,
        }
    try:
        parsed = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return {
            "selected_skills": [],
            "confidence": 0.0,
            "reason": "LLM skill selection did not return valid JSON.",
            "raw_response": raw,
            "fallback": True,
        }
    if not isinstance(parsed, dict):
        return {
            "selected_skills": [],
            "confidence": 0.0,
            "reason": "LLM skill selection JSON was not an object.",
            "raw_response": raw,
            "fallback": True,
        }
    parsed["raw_response"] = raw
    return parsed


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _save_state(state: BSPAgentState) -> None:
    state.touch()
    state.save()


def _checkpoint_path(state: BSPAgentState) -> str:
    return str(Path(state.run_dir) / "checkpoints.sqlite")


def _graph_config(state: BSPAgentState) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": state.run_id}}


@contextmanager
def _sqlite_checkpointer(state: BSPAgentState) -> Iterator[SqliteSaver]:
    serializer = JsonPlusSerializer(allowed_msgpack_modules=()).with_msgpack_allowlist(
        [BSPAgentState, Settings]
    )
    conn = sqlite3.connect(_checkpoint_path(state), check_same_thread=False)
    try:
        yield SqliteSaver(conn, serde=serializer)
    finally:
        conn.close()
