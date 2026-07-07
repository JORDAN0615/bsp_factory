from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent import observability
from agent.tools.edit_agent_tools import edit_file, editable_repo
from agent.tools.readonly_tools import grep_repo, read_file, readonly_repo

if TYPE_CHECKING:
    from agent.config import Settings


PATCH_SYSTEM_PROMPT = """You are a conservative Jetson BSP editor.
Read the relevant files with read_file or grep_repo before editing. Use
edit_file to make minimal edits in the staging repo only. After each edit,
re-read the file to confirm the change applied. Never invent files or board
facts. If no safe change exists, make no edits and say so. Do not output a diff.
"""


def run_patch_agent(
    staging_path: str | Path,
    issue: str,
    skill_text: str,
    repo_inspection: str,
    retry_context: str,
    settings: "Settings",
    recursion_limit: int | None = None,
) -> None:
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langgraph.errors import GraphRecursionError

    from agent.tools.llm_tools import LLMError, transient_llm_errors

    model = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=0,
        timeout=settings.llm_timeout_sec,
        max_retries=settings.llm_max_retries,
    )
    agent = create_agent(
        model=model,
        tools=[grep_repo, read_file, edit_file],
        system_prompt=PATCH_SYSTEM_PROMPT,
    )
    limit = recursion_limit or settings.evidence_recursion_limit
    config: dict[str, Any] = {"recursion_limit": limit}
    handler = observability.langchain_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    prompt = (
        "Edit the staged BSP repo if a safe minimal fix is supported by evidence.\n\n"
        f"Issue:\n{issue}\n\n"
        f"Retry context:\n{retry_context[:8000]}\n\n"
        f"Retrieved skills:\n{skill_text[:20000]}\n\n"
        f"Repo inspection hints:\n{repo_inspection[:40000]}\n\n"
        "Use read_file/grep_repo first, edit with edit_file only, then re-read to confirm."
    )
    try:
        with readonly_repo(staging_path), editable_repo(staging_path):
            for _chunk in agent.stream(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                stream_mode="values",
            ):
                pass
    except GraphRecursionError:
        return
    except transient_llm_errors() as exc:
        # Normalize to LLMError so the graph layer only handles one type. The
        # partial staging edits are the caller's to dump/discard.
        raise LLMError(str(exc)) from exc
