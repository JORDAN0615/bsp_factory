from __future__ import annotations

import sqlite3
import json
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent import observability
from agent.config import Settings
from agent.state import BSPAgentState
from agent.tools.artifact_tools import write_json, write_text
from agent.tools.edit_tools import EditError, apply_edits, parse_edit_blocks, preview_diff
from agent.tools.git_tools import (
    GitError,
    add_worktree,
    checkout_branch,
    commit_all,
    diff_worktree,
    push_branch,
    remove_worktree,
)
from agent.tools.llm_tools import LLMConfig, LLMError, chat_completion, strip_json_fence
from agent.tools.patch_tools import (
    PatchError,
    apply_patch,
    changed_files_from_diff,
    check_patch,
    extract_diff_from_patch_md,
)
from agent.tools.review_tools import run_code_review
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
    patch_format: str
    no_patch_reason: str | None
    validate_route: str
    no_patch_route: str
    review_agent_route: str
    review_route: str


def build_repair_graph(checkpointer=None):
    graph = StateGraph(RepairGraphState)
    graph.add_node("classify_error", classify_error_node)
    graph.add_node("select_skills", select_skills_node)
    graph.add_node("load_skill", load_skill_node)
    graph.add_node("inspect_repo", inspect_repo_node)
    graph.add_node("patch_agent", patch_agent_node)
    graph.add_node("write_no_patch", write_no_patch_node)
    graph.add_node("validate_patch", validate_patch_node)
    graph.add_node("code_review_agent", code_review_agent_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("apply_patch", apply_patch_node)
    graph.add_node("publish", publish_node)

    graph.add_edge(START, "classify_error")
    graph.add_edge("classify_error", "select_skills")
    graph.add_edge("select_skills", "load_skill")
    graph.add_edge("load_skill", "inspect_repo")
    graph.add_edge("inspect_repo", "patch_agent")
    graph.add_conditional_edges(
        "patch_agent",
        route_after_patch_agent,
        {
            "write_no_patch": "write_no_patch",
            "validate_patch": "validate_patch",
            "human_review": "human_review",
        },
    )
    graph.add_conditional_edges(
        "write_no_patch",
        route_after_no_patch,
        {
            "classify_error": "classify_error",
            "human_review": "human_review",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "validate_patch",
        route_after_validate_patch,
        {
            "write_no_patch": "write_no_patch",
            "code_review_agent": "code_review_agent",
            "human_review": "human_review",
        },
    )
    graph.add_conditional_edges(
        "code_review_agent",
        route_after_code_review,
        {
            "classify_error": "classify_error",
            "human_review": "human_review",
        },
    )
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "apply_patch": "apply_patch",
            "classify_error": "classify_error",
            "end": END,
        },
    )
    graph.add_edge("apply_patch", "publish")
    graph.add_edge("publish", END)
    return graph.compile(checkpointer=checkpointer)


def run_repair_graph(state: BSPAgentState, settings: Settings) -> BSPAgentState:
    logs_text = [Path(path).read_text(errors="replace", encoding="utf-8") for path in state.input_logs]
    with _sqlite_checkpointer(state) as checkpointer:
        config = _graph_config(state)
        handler = observability.langchain_handler()
        if handler is not None:
            config = _with_observability_config(config, state, handler)
        try:
            with observability.run_span(state.run_id, state.issue):
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
                    config=config,
                )
        finally:
            observability.flush()
    if result and "state" in result:
        return result["state"]
    return BSPAgentState.load(state.run_dir)


def resume_review_graph(
    state: BSPAgentState,
    settings: Settings,
    decision: dict[str, str],
) -> BSPAgentState:
    with _sqlite_checkpointer(state) as checkpointer:
        config = _graph_config(state)
        handler = observability.langchain_handler()
        if handler is not None:
            config = _with_observability_config(config, state, handler)
        try:
            with observability.run_span(state.run_id, state.issue):
                result = build_repair_graph(checkpointer).invoke(
                    Command(resume=decision, update={"settings": settings}),
                    config=config,
                )
        finally:
            observability.flush()
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

    write_json(_attempt_dir(state) / "debug" / "error_classification.json", classification)
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

    classification_path = _attempt_dir(state) / "debug" / "error_classification.json"
    if classification_path.exists():
        classification = read_json(classification_path)
    state.stage = "select_skills"
    catalog = build_skill_catalog(settings.skills_dir)
    write_json(_attempt_dir(state) / "debug" / "skill_catalog.json", catalog)
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
    write_json(_attempt_dir(state) / "debug" / "skill_selection.json", selection)
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

    write_text(
        _attempt_dir(state) / "debug" / "retrieved_skills.md",
        skill_text or "(No skills selected.)\n",
    )
    _save_state(state)
    return {"state": state, "skill_text": skill_text}


def inspect_repo_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    state.stage = "inspect_repo"
    from agent.nodes.workflow import _attempt_dir, _keywords_for_attempt, _repo_inspection_text

    def _deterministic_inspection(prefix: str = "") -> str:
        keywords = _keywords_for_attempt(state, attempt)
        candidates = list_candidate_files(state.repo_path, keywords) if keywords else []
        return prefix + _repo_inspection_text(state.repo_path, candidates)

    if settings.react_evidence_enabled:
        from agent.tools.react_evidence import gather_evidence

        try:
            repo_inspection = gather_evidence(
                state.repo_path,
                state.issue,
                attempt.selected_skills,
                settings,
                recursion_limit=settings.evidence_recursion_limit,
            )
        except LLMError as exc:
            # ReAct evidence hit a transient LLM failure before collecting any
            # rounds. Fall back to the deterministic keyword inspection so the
            # run keeps moving; the patch agent owns any escalation.
            repo_inspection = _deterministic_inspection(
                f"(ReAct evidence unavailable: {exc}; deterministic inspection used)\n\n"
            )
    else:
        repo_inspection = _deterministic_inspection()
    write_text(_attempt_dir(state) / "repo_inspection.md", repo_inspection)
    _save_state(state)
    return {"state": state, "repo_inspection": repo_inspection}


def patch_agent_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    state.stage = "propose_patch"
    from agent.nodes.workflow import _propose_patch

    skill_text = graph_state.get("skill_text", "")
    repo_inspection = graph_state.get("repo_inspection", "")
    if settings.patch_agent_agentic:
        from agent.nodes.workflow import _attempt_dir
        from agent.tools.patch_agent import run_patch_agent
        from agent.tools.retry_tools import build_retry_context

        rounds = 1 + settings.llm_failure_node_retries
        retry_context = build_retry_context(state)
        last_error: str | None = None
        diff_text = ""
        succeeded = False
        for round_no in range(1, rounds + 1):
            staging_path = Path(tempfile.mkdtemp(prefix=f"bsp-agent-{state.run_id}-"))
            try:
                staging_path.rmdir()
            except OSError:
                pass
            staging = str(staging_path)
            failed = False
            try:
                add_worktree(state.repo_path, staging)
                run_patch_agent(
                    staging,
                    state.issue,
                    skill_text,
                    repo_inspection,
                    retry_context,
                    settings,
                )
                diff_text = diff_worktree(staging)
            except LLMError as exc:
                # Transient LLM failure. Dump whatever the agent edited before
                # the failure for forensics, then discard the partial edits.
                last_error = str(exc)
                failed = True
                try:
                    partial = diff_worktree(staging)
                except Exception:
                    partial = ""
                if partial.strip():
                    write_text(
                        _attempt_dir(state) / "debug" / f"partial_patch_round{round_no}.diff",
                        partial,
                    )
            finally:
                remove_worktree(state.repo_path, staging)
                shutil.rmtree(staging, ignore_errors=True)
            if not failed:
                succeeded = True
                break
            if round_no < rounds:
                time.sleep(settings.llm_failure_retry_delay_sec)

        if not succeeded:
            # All rounds hit a transient LLM failure. Pause at human_review in
            # llm_failure mode without consuming the max_loops budget.
            state.failure_reason = (
                f"Patch Agent LLM unavailable after {rounds} round(s): {last_error}"
            )
            _save_state(state)
            return {
                "state": state,
                "diff_text": "",
                "no_patch_reason": None,
                "patch_format": "diff",
            }

        if not diff_text.strip():
            _save_state(state)
            return {
                "state": state,
                "diff_text": "NO_PATCH",
                "no_patch_reason": "Agentic patch agent made no edits.",
                "patch_format": "diff",
            }
        write_text(_attempt_dir(state) / "agentic_patch.diff", diff_text)
        _save_state(state)
        return {
            "state": state,
            "diff_text": diff_text,
            "no_patch_reason": None,
            "patch_format": "diff",
        }

    diff_text, no_patch_reason = _propose_patch(
        state,
        attempt,
        skill_text,
        repo_inspection,
        settings,
    )
    _save_state(state)
    return {
        "state": state,
        "diff_text": diff_text,
        "no_patch_reason": no_patch_reason,
        "patch_format": "edit_blocks",
    }


def route_after_patch_agent(
    graph_state: RepairGraphState,
) -> Literal["write_no_patch", "validate_patch", "human_review"]:
    if graph_state["state"].failure_reason:
        return "human_review"
    if graph_state.get("no_patch_reason") or graph_state.get("diff_text") == "NO_PATCH":
        return "write_no_patch"
    return "validate_patch"


def write_no_patch_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    from agent.nodes.workflow import _write_no_patch

    _write_no_patch(state, graph_state.get("no_patch_reason") or "No safe patch was proposed.")
    if attempt.patch_status != "failed":
        attempt.patch_status = "no_patch"
    if len(state.attempts) >= state.max_loops:
        if state.human_directed:
            state.stage = "human_review"
            _save_state(state)
            return {"state": state, "no_patch_route": "human_review"}
        state.stage = "report"
        _save_state(state)
        return {"state": state, "no_patch_route": "end"}
    state.new_attempt()
    state.stage = "classify_error"
    _save_state(state)
    return {"state": state, "no_patch_route": "classify_error", "no_patch_reason": None, "diff_text": ""}


def route_after_no_patch(graph_state: RepairGraphState) -> Literal["classify_error", "human_review", "end"]:
    route = graph_state.get("no_patch_route")
    if route == "classify_error":
        return "classify_error"
    if route == "human_review":
        return "human_review"
    return "end"


def validate_patch_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    state.stage = "validate_patch"
    patch_format = graph_state.get("patch_format") or "edit_blocks"
    patch_input = graph_state.get("diff_text", "")
    from agent.nodes.workflow import _attempt_dir, _patch_markdown

    try:
        if patch_format == "diff":
            diff_text = patch_input
            check_patch(state.repo_path, diff_text)
        else:
            blocks = parse_edit_blocks(patch_input)
            diff_text = preview_diff(state.repo_path, blocks)
    except (EditError, PatchError) as exc:
        attempt.patch_status = "failed"
        _save_state(state)
        prefix = "Edit validation failed" if isinstance(exc, EditError) else "Patch validation failed"
        return {
            "state": state,
            "no_patch_reason": f"{prefix}: {exc}",
            "validate_route": "write_no_patch",
        }

    attempt.changed_files = changed_files_from_diff(diff_text)
    if patch_format == "diff":
        write_text(_attempt_dir(state) / "agentic_patch.diff", diff_text)
    else:
        write_text(_attempt_dir(state) / "edits.md", patch_input)
    write_text(
        _attempt_dir(state) / "patch.md",
        _patch_markdown(attempt, diff_text),
    )
    attempt.patch_status = "generated"
    _save_state(state)
    return {
        "state": state,
        "diff_text": diff_text,
        "patch_format": patch_format,
        "validate_route": "code_review_agent",
    }


def route_after_validate_patch(
    graph_state: RepairGraphState,
) -> Literal["write_no_patch", "code_review_agent", "human_review"]:
    if graph_state.get("validate_route") == "write_no_patch":
        return "write_no_patch"
    if graph_state["settings"].code_review_enabled:
        return "code_review_agent"
    return "human_review"


def code_review_agent_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    attempt = state.current_attempt
    state.stage = "code_review"
    review = run_code_review(
        state,
        attempt,
        graph_state.get("diff_text", ""),
        graph_state.get("repo_inspection", ""),
        settings,
    )
    if review["decision"] == "reject":
        if len(state.attempts) >= state.max_loops:
            # Retry budget exhausted: escalate to human review as the fallback.
            _save_state(state)
            return {"state": state, "review_agent_route": "human_review"}
        state.new_attempt()
        state.stage = "classify_error"
        _save_state(state)
        return {
            "state": state,
            "review_agent_route": "classify_error",
            "no_patch_reason": None,
            "diff_text": "",
        }
    _save_state(state)
    return {"state": state, "review_agent_route": "human_review"}


def route_after_code_review(
    graph_state: RepairGraphState,
) -> Literal["classify_error", "human_review"]:
    route = graph_state.get("review_agent_route")
    if route == "classify_error":
        return "classify_error"
    return "human_review"


def human_review_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    attempt = state.current_attempt
    from agent.nodes.workflow import _attempt_dir

    # failure_reason is the mode discriminator and is persisted, so the mode is
    # stable across the interrupt/resume boundary.
    mode = "llm_failure" if state.failure_reason else "patch_review"
    if mode == "patch_review":
        # A human is now making a quality judgment; the run is human-directed for
        # the rest of its life (ADR-0009). An LLM-failure pause is not a quality
        # judgment, so it must not flip this flag.
        state.human_directed = True
    state.stage = "human_review"
    _save_state(state)

    if mode == "llm_failure":
        payload = {
            "type": "human_review",
            "mode": "llm_failure",
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "attempt_no": attempt.attempt_no,
            "failure_reason": state.failure_reason,
            "message": "The LLM was unavailable. Resume with retry or abandon.",
        }
    else:
        payload = {
            "type": "human_review",
            "mode": "patch_review",
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "attempt_no": attempt.attempt_no,
            "patch_status": attempt.patch_status,
            "changed_files": attempt.changed_files,
            "patch_path": str(_attempt_dir(state) / "patch.md"),
            "code_review_path": str(_attempt_dir(state) / "code_review.md"),
            "code_review_decision": attempt.code_review_decision,
            "message": "Review the patch and resume with approve or reject.",
        }
    decision = interrupt(payload)
    action = decision.get("action") if isinstance(decision, dict) else None

    if action == "retry":
        if mode != "llm_failure":
            raise RuntimeError("retry is only valid for an LLM-failure pause")
        # Re-run the same attempt from the top without consuming max_loops.
        state.failure_reason = None
        state.stage = "classify_error"
        _save_state(state)
        return {
            "state": state,
            "review_route": "classify_error",
            "no_patch_reason": None,
            "diff_text": "",
        }
    if mode == "llm_failure":
        raise RuntimeError("run is paused on an LLM failure; use retry or abandon")

    if action == "approve":
        if attempt.patch_status != "generated":
            raise RuntimeError(
                f"Cannot approve attempt with patch status {attempt.patch_status}."
            )
        attempt.human_review_status = "approved"
        (_attempt_dir(state) / "review.md").write_text("Status: approved\n", encoding="utf-8")
        _save_state(state)
        return {"state": state, "review_route": "apply_patch"}
    if action == "reject":
        feedback = ""
        if isinstance(decision, dict):
            feedback = str(decision.get("feedback") or "")
        attempt.human_review_status = "rejected"
        attempt.human_feedback = feedback
        (_attempt_dir(state) / "review.md").write_text(
            f"Status: rejected\n\nFeedback:\n{feedback}\n", encoding="utf-8"
        )
        state.new_attempt()
        state.stage = "classify_error"
        _save_state(state)
        return {
            "state": state,
            "review_route": "classify_error",
            "no_patch_reason": None,
            "diff_text": "",
        }
    raise RuntimeError(f"Unknown human review action: {action}")


def route_after_human_review(
    graph_state: RepairGraphState,
) -> Literal["apply_patch", "classify_error", "end"]:
    route = graph_state.get("review_route")
    if route == "classify_error":
        return "classify_error"
    if route == "apply_patch":
        return "apply_patch"
    return "end"


def apply_patch_node(graph_state: RepairGraphState) -> RepairGraphState:
    """Apply the accepted edit blocks to the working tree."""
    state = graph_state["state"]
    attempt = state.current_attempt
    state.stage = "apply_patch"
    from agent.nodes.workflow import _attempt_dir, _write_no_patch

    try:
        edits_path = _attempt_dir(state) / "edits.md"
        if edits_path.exists():
            blocks = parse_edit_blocks(edits_path.read_text(encoding="utf-8"))
            apply_edits(state.repo_path, blocks, write=True)
        else:
            patch_path = _attempt_dir(state) / "patch.md"
            diff_text = extract_diff_from_patch_md(patch_path.read_text(encoding="utf-8"))
            apply_patch(state.repo_path, diff_text)
    except (EditError, PatchError, OSError) as exc:
        _write_no_patch(state, f"Accepted edits failed to apply: {exc}")
        attempt.patch_status = "failed"
        state.stage = "failed"
        _save_state(state)
        return {"state": state}
    attempt.patch_status = "applied"
    state.stage = "target_ready"
    _save_state(state)
    return {"state": state}


def publish_node(graph_state: RepairGraphState) -> RepairGraphState:
    state = graph_state["state"]
    settings = graph_state["settings"]
    return {"state": _do_publish(state, settings)}


def _do_publish(state: BSPAgentState, settings: Settings) -> BSPAgentState:
    attempt = state.current_attempt
    if attempt.patch_status != "applied":
        _save_state(state)
        return state
    if not settings.auto_push_enabled:
        _save_state(state)
        return state

    state.stage = "publish"
    branch = f"bsp-agent/{state.run_id}"
    attempt.published_branch = branch
    from agent.nodes.workflow import _publish_commit_message, _write_publish_artifact

    # Commit step. published_commit being set means commit succeeded; the CLI uses
    # that to tell whether a failure happened at the commit or the push stage.
    try:
        try:
            checkout_branch(state.repo_path, branch, create=True)
        except GitError as exc:
            if "already exists" not in str(exc):
                raise
            checkout_branch(state.repo_path, branch, create=False)
        sha = commit_all(state.repo_path, _publish_commit_message(state, attempt))
    except GitError as exc:
        attempt.publish_status = "failed"
        attempt.publish_error = str(exc)
        state.stage = "publish_failed"
        _write_publish_artifact(state, attempt, settings.git_remote)
        _save_state(state)
        return state
    attempt.published_commit = sha

    # Push step.
    try:
        push_branch(state.repo_path, settings.git_remote, branch)
    except GitError as exc:
        attempt.publish_status = "failed"
        attempt.publish_error = str(exc)
        state.stage = "publish_failed"
        _write_publish_artifact(state, attempt, settings.git_remote)
        _save_state(state)
        return state

    attempt.publish_status = "pushed"
    attempt.publish_error = None
    state.stage = "published"
    _write_publish_artifact(state, attempt, settings.git_remote)
    _save_state(state)
    return state


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
            timeout_sec=settings.llm_timeout_sec,
            name="select_skills",
        )
    except LLMError as exc:
        return {
            "selected_skills": [],
            "confidence": 0.0,
            "reason": f"LLM skill selection unavailable: {exc}",
            "fallback": True,
        }
    try:
        parsed = json.loads(strip_json_fence(raw))
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


def _save_state(state: BSPAgentState) -> None:
    state.touch()
    state.save()


def _checkpoint_path(state: BSPAgentState) -> str:
    return str(Path(state.run_dir) / "checkpoints.sqlite")


def _graph_config(state: BSPAgentState) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": state.run_id}}


def _with_observability_config(config: dict, state: BSPAgentState, handler) -> dict:
    metadata = {
        **config.get("metadata", {}),
        "issue": state.issue[:500],
        "langfuse_session_id": state.run_id,
        "langfuse_trace_name": f"run:{state.run_id}",
        "langfuse_tags": ["bsp-agent"],
    }
    tags = list(dict.fromkeys([*config.get("tags", []), "bsp-agent"]))
    return {**config, "callbacks": [handler], "metadata": metadata, "tags": tags}


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
