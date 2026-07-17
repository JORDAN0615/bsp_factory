from __future__ import annotations

import json
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

from agent import observability
from agent.tools.edit_agent_tools import editable_repo, replace_in_editable_repo
from agent.tools.skill_tools import build_skill_catalog, read_skill_folder

if TYPE_CHECKING:
    from agent.config import Settings


DEEP_PATCH_SYSTEM_PROMPT = """You are the Deep Patch Agent for a Jetson BSP repair workflow.

Your job is to investigate the staged BSP source tree and make the smallest safe fix
supported by the issue, the Jetson skills you load, and MIC-741 repair knowledge.

Operating rules:
- Plan the investigation before editing. Use the filesystem read tools to locate and
  read the exact device-tree, Kconfig, driver, or configuration code involved.
- Call list_skills to discover the available Jetson BSP skills, then load_skill(name)
  to read the one matching this issue's subsystem (pinmux, camera, can, mgbe, pcie, …)
  before you edit files in that area. Do not edit a subsystem whose skill you have not read.
- Delegate a bounded read-only investigation to the general-purpose researcher when
  that will reduce uncertainty. The researcher cannot edit files.
- The built-in write_file and edit_file tools are denied. Modify existing files only
  with stage_edit_file after reading the exact current text.
- After every successful edit, re-read the changed region and verify it matches the
  intended repair. Fix tool errors in-loop instead of guessing.
- Never invent files, symbols, board facts, register values, or version-specific
  behavior. If the evidence is insufficient, leave the staging tree unchanged.
- Do not create files, run shell commands, commit, push, build, flash, or output a diff.
  The outer deterministic workflow owns validation, review, apply, and publish.
"""


READ_ONLY_RESEARCH_PROMPT = """Investigate the Jetson BSP issue in the mounted repository.
Use only ls, glob, grep, and read_file. Follow concrete symbols and include chains only
as far as the repository supports them. Return exact file paths, relevant line ranges,
and unresolved gaps. Never attempt to edit or create files.
"""


def _virtual_path_to_repo_relative(file_path: str) -> str:
    value = file_path.strip()
    if not value:
        return value
    if ".." in PurePath(value).parts:
        return value
    return value.lstrip("/")


@tool
def stage_edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Replace exact text in an existing file in the current staging worktree only."""
    path = _virtual_path_to_repo_relative(file_path)
    return replace_in_editable_repo(path, old_string, new_string, replace_all)


def _build_skill_tools(settings: "Settings", loaded_skills: list[str]):
    """On-demand skill discovery tools (ADR-0017). Backed by the existing skill
    loader; load_skill records what the agent read so the node can populate
    RepairAttempt.selected_skills for downstream review/reporting."""
    skills_dir = settings.skills_dir

    @tool
    def list_skills() -> str:
        """List the available Jetson BSP skills, each with a one-line description.
        Call this first to find which skill matches the issue's subsystem
        (pinmux, camera, can, mgbe, pcie, ...), then load the relevant one."""
        catalog = build_skill_catalog(skills_dir)
        if not catalog:
            return "(no skills available)"
        return json.dumps(catalog, ensure_ascii=False, indent=2)

    @tool
    def load_skill(name: str) -> str:
        """Load the full text of one Jetson BSP skill by its folder name (the
        'folder' field from list_skills). Read it before editing that subsystem."""
        try:
            text = read_skill_folder(skills_dir, name)
        except Exception as exc:  # noqa: BLE001
            return f"(error: {exc}; call list_skills for valid folder names)"
        loaded_skills.append(name)
        return text

    return [list_skills, load_skill]


def build_deep_patch_agent(
    staging_path: str | Path,
    settings: "Settings",
    loaded_skills: list[str] | None = None,
):
    """Build the Deep Agents harness against a staging-only filesystem backend."""
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI

    skill_tools = _build_skill_tools(settings, loaded_skills if loaded_skills is not None else [])

    model = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=0,
        timeout=settings.llm_timeout_sec,
        max_retries=settings.llm_max_retries,
    )
    backend = FilesystemBackend(root_dir=Path(staging_path), virtual_mode=True)
    deny_builtin_writes = [
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")
    ]
    researcher = {
        # Naming this general-purpose replaces the default subagent. Declaring
        # tools=[] prevents the custom staging edit tool from being inherited.
        "name": "general-purpose",
        "description": "Read-only Jetson BSP source investigator for delegated research.",
        "system_prompt": READ_ONLY_RESEARCH_PROMPT,
        "tools": [],
        "permissions": deny_builtin_writes,
    }
    return create_deep_agent(
        model=model,
        tools=[stage_edit_file, *skill_tools],
        system_prompt=DEEP_PATCH_SYSTEM_PROMPT,
        subagents=[researcher],
        backend=backend,
        permissions=deny_builtin_writes,
        name="bsp_deep_patch_agent",
    )


def run_deep_patch_agent(
    staging_path: str | Path,
    issue: str,
    skill_text: str,
    knowledge_context: str,
    retry_context: str,
    settings: "Settings",
    recursion_limit: int | None = None,
    loaded_skills: list[str] | None = None,
    guide: str = "",
) -> None:
    """Run one bounded Deep Agent investigation-and-edit session on staging.

    The agent discovers and reads Jetson skills itself via the list_skills /
    load_skill tools (ADR-0017); names it loads are appended to ``loaded_skills``.
    ``skill_text`` remains an optional preload used by the legacy path and tests.
    ``guide`` is the planner's repair guide (ADR-0020); when present the executor
    implements it precisely instead of deciding the fix itself.
    """
    from langgraph.errors import GraphRecursionError

    from agent.tools.llm_tools import LLMError, transient_llm_errors

    agent = build_deep_patch_agent(staging_path, settings, loaded_skills=loaded_skills)
    limit = recursion_limit or settings.deep_agent_recursion_limit
    config: dict[str, Any] = {"recursion_limit": limit}
    handler = observability.langchain_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    guide_block = ""
    if guide.strip():
        guide_block = (
            "A planner has already decided the fix. Implement this guide precisely: "
            "for each change, read the file, locate the spot from location_hint, and "
            "apply the described edit. Verify against the acceptance checks. Do not "
            "re-plan or deviate unless the real file contradicts the guide.\n\n"
            f"Repair guide:\n{guide[:40000]}\n\n"
        )
    prompt = (
        "Investigate and repair the issue in the staged repository. Keep working until "
        "the minimal edit is made and verified, or conclude that no safe edit exists.\n\n"
        f"Issue:\n{issue}\n\n"
        f"{guide_block}"
        f"Retry context from earlier attempts:\n{retry_context[:8000]}\n\n"
        "Call list_skills to discover the Jetson BSP skills, then load_skill(name) to "
        "read the one matching this issue's subsystem before editing.\n\n"
        f"Preloaded Jetson BSP skills (may be empty — use the skill tools if so):\n"
        f"{skill_text[:24000]}\n\n"
        f"Retrieved MIC-741 repair knowledge:\n{knowledge_context[:60000]}\n\n"
        "Repository files are mounted at virtual path /. Read before editing. "
        "Use stage_edit_file for every modification and re-read each changed region."
    )
    try:
        with editable_repo(staging_path):
            for _chunk in agent.stream(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                stream_mode="values",
            ):
                pass
    except GraphRecursionError:
        # Preserve any verified partial edits in staging. The outer node turns
        # them into a diff and the normal validation/review gates still apply.
        return
    except transient_llm_errors() as exc:
        raise LLMError(str(exc)) from exc
