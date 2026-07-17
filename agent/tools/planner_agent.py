from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent import observability
from agent.tools.deep_patch_agent import _build_skill_tools

if TYPE_CHECKING:
    from agent.config import Settings


PLANNER_SYSTEM_PROMPT = """You are the Planner for a Jetson BSP repair workflow.

You run on a strong cloud model. A separate, weaker local executor will implement
your guide, so your job is to DECIDE the correct fix precisely — the executor cannot
figure out the fix on its own. You are READ-ONLY: you never edit files.

Operating rules:
- Investigate first. Use ls/glob/grep/read_file to read the exact device-tree,
  Kconfig, driver, or configuration code involved. Call list_skills, then
  load_skill(name) for the subsystem in play (pinmux, camera, can, mgbe, pcie, …),
  and use the retrieved MIC-741 repair knowledge.
- Never invent files, symbols, board facts, or register values. Only reference files
  and text you have actually read.
- Produce a guide precise enough that the executor does NOT have to decide anything:
  say exactly WHAT to change and WHERE (file + how to locate the spot + the change),
  but do NOT write a full diff — the executor reads the real file and makes the edit.

Output ONLY the guide as a JSON object in a ```json fenced block, matching:

{
  "root_cause": "one paragraph: the fault, localized to concrete code",
  "strategy": "one paragraph: the fix approach",
  "changes": [
    {
      "file": "<repo-relative path you have read>",
      "intent": "what this change achieves",
      "location_hint": "how to find the exact spot: node/symbol/section + a nearby anchor line",
      "edit": "the precise change: what to set/add/remove and to what value (NOT a full diff)",
      "reference": "optional: MIC-741 case id or skill section this mirrors"
    }
  ],
  "acceptance": ["observable completion checks, e.g. 'all 8 i2c pins present'"],
  "avoid": ["what not to touch; common mistakes on this subsystem"]
}

If the evidence is insufficient for a safe fix, return a guide whose "changes" is an
empty list and explain why in "strategy".
"""


PLANNER_RESEARCH_PROMPT = """Investigate the Jetson BSP issue in the mounted repository.
Use only ls, glob, grep, and read_file. Follow concrete symbols and include chains only
as far as the repository supports them. Return exact file paths, relevant line ranges,
and unresolved gaps. Never attempt to edit or create files.
"""


def _final_message_text(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    if isinstance(content, str):
        return content
    # Some models return a list of content blocks.
    parts = []
    for block in content:
        if isinstance(block, dict):
            parts.append(str(block.get("text", "")))
        else:
            parts.append(str(block))
    return "".join(parts)


def build_planner_agent(
    repo_path: str | Path,
    settings: "Settings",
    loaded_skills: list[str] | None = None,
):
    """Build a READ-ONLY Deep Agents harness for planning (ADR-0020).

    Rooted at the real repo (no worktree — it never edits). No stage_edit_file and
    all built-in writes denied, so the planner can only read, discover skills, and
    delegate read-only research.
    """
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI

    skill_tools = _build_skill_tools(settings, loaded_skills if loaded_skills is not None else [])

    model = ChatOpenAI(
        base_url=settings.planner_llm_base_url,
        api_key=settings.planner_llm_api_key,
        model=settings.planner_llm_model,
        temperature=0,
        timeout=settings.planner_llm_timeout_sec,
        max_retries=settings.llm_max_retries,
    )
    backend = FilesystemBackend(root_dir=Path(repo_path), virtual_mode=True)
    deny_builtin_writes = [
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")
    ]
    researcher = {
        "name": "general-purpose",
        "description": "Read-only Jetson BSP source investigator for delegated research.",
        "system_prompt": PLANNER_RESEARCH_PROMPT,
        "tools": [],
        "permissions": deny_builtin_writes,
    }
    return create_deep_agent(
        model=model,
        tools=list(skill_tools),
        system_prompt=PLANNER_SYSTEM_PROMPT,
        subagents=[researcher],
        backend=backend,
        permissions=deny_builtin_writes,
        name="bsp_planner_agent",
    )


def run_planner_agent(
    repo_path: str | Path,
    issue: str,
    knowledge_context: str,
    retry_context: str,
    settings: "Settings",
    recursion_limit: int | None = None,
    loaded_skills: list[str] | None = None,
) -> str:
    """Run one bounded read-only planning session and return the repair guide text.

    Raises LLMError on a transient cloud failure so the node can apply ADR-0012
    degradation. A recursion-limit stop returns whatever guide text was produced.
    """
    from langgraph.errors import GraphRecursionError

    from agent.tools.llm_tools import LLMError, transient_llm_errors

    agent = build_planner_agent(repo_path, settings, loaded_skills=loaded_skills)
    limit = recursion_limit or settings.planner_recursion_limit
    config: dict[str, Any] = {"recursion_limit": limit}
    handler = observability.langchain_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    prompt = (
        "Investigate the issue in the mounted repository and produce the repair guide.\n\n"
        f"Issue:\n{issue}\n\n"
        f"Retry context from earlier attempts:\n{retry_context[:8000]}\n\n"
        "Call list_skills, then load_skill(name) for the relevant subsystem.\n\n"
        f"Retrieved MIC-741 repair knowledge:\n{knowledge_context[:60000]}\n\n"
        "Repository files are mounted at virtual path /. Read the exact code before "
        "deciding the fix. Output ONLY the JSON guide."
    )
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config=config,
        )
        return _final_message_text(result).strip()
    except GraphRecursionError:
        return ""
    except transient_llm_errors() as exc:
        raise LLMError(str(exc)) from exc
