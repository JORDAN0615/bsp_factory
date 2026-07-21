from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent import observability
from agent.tools.deep_patch_agent import mount_skills
from agent.tools.knowledge_tool import build_bsp_knowledge_tool

if TYPE_CHECKING:
    from agent.config import Settings


PLANNER_SYSTEM_PROMPT = """You are the Planner for a Jetson BSP repair workflow.

You run on a strong cloud model. A separate, weaker local executor will implement
your guide, so your job is to DECIDE the correct fix precisely — the executor cannot
figure out the fix on its own. You are READ-ONLY: you never edit files.

Operating rules:
- Investigate first. Use ls/glob/grep/read_file to read the exact device-tree,
  Kconfig, driver, or configuration code involved. Read the Jetson skill for the
  subsystem in play (pinmux, camera, can, mgbe, pcie, …) from the skills library,
  and call search_bsp_knowledge(query) to retrieve relevant past repairs, Git patch
  excerpts, vendor design-guide/datasheet facts, and pinmux records. Reformulate and
  call it again as your understanding sharpens.
- If the issue, repository, or loaded skill contains a relevant URL and
  fetch_web_page is available, you MUST fetch that exact URL before concluding.
  Prefer official vendor documentation. Never invent or modify a URL, and never put
  repository content into a URL. This tool retrieves a known URL; it does not search.
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


def build_planner_agent(root_path: str | Path, settings: "Settings"):
    """Build a READ-ONLY Deep Agents harness for planning (ADR-0020).

    ``root_path`` is a disposable working copy (a staging worktree) — skills are
    mounted into it as an untracked dir and all built-in writes are denied, so the
    planner only reads the repo, discovers skills, queries RAG, and delegates
    read-only research. Never pass the real repo (mount_skills writes into it).
    """
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI

    skills = mount_skills(root_path, settings.skills_dir)
    tools = [build_bsp_knowledge_tool(settings)]
    if settings.web_fetch_enabled:
        from agent.tools.web_tools import build_web_fetch_tool

        tools.append(build_web_fetch_tool(settings))

    model = ChatOpenAI(
        base_url=settings.planner_llm_base_url,
        api_key=settings.planner_llm_api_key,
        model=settings.planner_llm_model,
        temperature=0,
        timeout=settings.planner_llm_timeout_sec,
        max_retries=settings.llm_max_retries,
    )
    backend = FilesystemBackend(root_dir=Path(root_path), virtual_mode=True)
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
        tools=tools,
        skills=skills or None,
        system_prompt=PLANNER_SYSTEM_PROMPT,
        subagents=[researcher],
        backend=backend,
        permissions=deny_builtin_writes,
        name="bsp_planner_agent",
    )


def run_planner_agent(
    repo_path: str | Path,
    issue: str,
    retry_context: str,
    settings: "Settings",
    recursion_limit: int | None = None,
) -> str:
    """Run one bounded read-only planning session and return the repair guide text.

    Uses a disposable staging worktree as the backend root so skills can be mounted
    without touching the real repo. Raises LLMError on a transient cloud failure so
    the node can apply ADR-0012 degradation; a recursion-limit stop returns whatever
    guide text was produced.
    """
    import shutil
    import tempfile

    from langgraph.errors import GraphRecursionError

    from agent.tools.git_tools import add_worktree, remove_worktree
    from agent.tools.llm_tools import LLMError, transient_llm_errors

    staging_path = Path(tempfile.mkdtemp(prefix="bsp-planner-"))
    try:
        staging_path.rmdir()
    except OSError:
        pass
    staging = str(staging_path)

    limit = recursion_limit or settings.planner_recursion_limit
    config: dict[str, Any] = {"recursion_limit": limit}
    handler = observability.langchain_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    prompt = (
        "Investigate the issue in the mounted repository and produce the repair guide.\n\n"
        f"Issue:\n{issue}\n\n"
        f"Retry context from earlier attempts:\n{retry_context[:8000]}\n\n"
        "Read the Jetson skill for the relevant subsystem (from the skills library) "
        "and call search_bsp_knowledge(query) for relevant repair knowledge.\n\n"
        "Repository files are mounted at virtual path /. Read the exact code before "
        "deciding the fix. Output ONLY the JSON guide."
    )
    try:
        add_worktree(repo_path, staging)
        agent = build_planner_agent(staging, settings)
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config=config,
        )
        return _final_message_text(result).strip()
    except GraphRecursionError:
        return ""
    except transient_llm_errors() as exc:
        raise LLMError(str(exc)) from exc
    finally:
        remove_worktree(repo_path, staging)
        shutil.rmtree(staging, ignore_errors=True)
