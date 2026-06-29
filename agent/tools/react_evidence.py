from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent import observability
from agent.tools.readonly_tools import grep_repo, read_file, readonly_repo

if TYPE_CHECKING:
    from agent.config import Settings


SYSTEM_PROMPT = """You are an independent Jetson BSP evidence gatherer.
Use the read-only tools to locate the code relevant to the issue, following this
chain only as far as the repo actually supports it:
dmesg symptom -> device-tree node -> compatible string -> driver -> Kconfig.

Stop conditions -- obey these strictly:
- Budget about 5-6 tool calls total. Spend them; do not keep searching after that.
- Once you have found and read the device-tree node (or file) named in the issue,
  that is usually enough -- stop and write your findings.
- If a grep returns "(no matches)", do NOT retry variants of the same query. Treat
  it as "not present" and move on.
- Do not hunt for the include board files, driver, or Kconfig if they do not
  turn up in the first search or two. List anything you could not find under a
  "Missing:" note in your findings instead of searching further.

When you stop, write a concise plain-text findings summary that cites the exact
files and lines you read. Never guess. Do not produce a diff.
"""

_MAX_TOOL_BULLETS = 40
_MAX_PREVIEW_CHARS = 200


def gather_evidence(
    repo_path: str | Path,
    issue: str,
    selected_skills: list[str],
    settings: "Settings",
    recursion_limit: int | None = None,
) -> str:
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langgraph.errors import GraphRecursionError

    model = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=0,
    )
    agent = create_agent(
        model=model,
        tools=[grep_repo, read_file],
        system_prompt=SYSTEM_PROMPT,
    )
    limit = recursion_limit or settings.evidence_recursion_limit
    config: dict[str, Any] = {"recursion_limit": limit}
    handler = observability.langchain_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    prompt = (
        "Gather read-only source evidence for this BSP repair task.\n\n"
        f"Issue:\n{issue}\n\n"
        f"Selected skills:\n{', '.join(selected_skills) or '(none)'}\n\n"
        "Use tools as needed, then write concise findings. Do not propose a diff."
    )
    try:
        with readonly_repo(repo_path):
            result = agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
            )
    except GraphRecursionError:
        return render_evidence_md(
            messages=[],
            findings=f"(investigation did not converge within {limit} rounds)",
        )
    messages = result.get("messages", []) if isinstance(result, dict) else []
    return render_evidence_md(messages=messages)


def render_evidence_md(messages: list[Any], findings: str | None = None) -> str:
    final_text = findings if findings is not None else _final_ai_text(messages)
    bullets = _investigation_bullets(messages)
    lines = [
        "## Findings",
        "",
        final_text or "(no findings produced)",
        "",
        f"## Investigation ({len(bullets)} rounds)",
        "",
    ]
    if bullets:
        lines.extend(bullets)
    else:
        lines.append("- (no tool calls recorded)")
    lines.append("")
    return "\n".join(lines)


def _final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if _tool_calls(message):
            continue
        if _message_type(message) == "tool":
            continue
        content = _message_content(message)
        if content:
            return content
    return ""


def _investigation_bullets(messages: list[Any]) -> list[str]:
    bullets: list[str] = []
    pending: list[str] = []
    for message in messages:
        for call in _tool_calls(message):
            pending.append(_format_tool_call(call))
        if _message_type(message) == "tool":
            call = pending.pop(0) if pending else _tool_name(message)
            bullets.append(f"- {call} -> {_tool_result_preview(message)}")
            if len(bullets) >= _MAX_TOOL_BULLETS:
                bullets.append(f"- ... capped at {_MAX_TOOL_BULLETS} tool results")
                return bullets
    for call in pending[: max(0, _MAX_TOOL_BULLETS - len(bullets))]:
        bullets.append(f"- {call} -> (no tool result recorded)")
    return bullets


def _tool_calls(message: Any) -> list[dict[str, Any]]:
    calls = getattr(message, "tool_calls", None)
    if calls is None and isinstance(message, dict):
        calls = message.get("tool_calls")
    return list(calls or [])


def _format_tool_call(call: dict[str, Any]) -> str:
    name = str(call.get("name") or "tool")
    args = call.get("args") or {}
    if not isinstance(args, dict):
        return f"{name}(...)"
    rendered_args = ", ".join(f"{key}={value!r}" for key, value in args.items())
    return f"{name}({rendered_args})"


def _message_type(message: Any) -> str:
    msg_type = getattr(message, "type", None)
    if msg_type is None and isinstance(message, dict):
        msg_type = message.get("type") or message.get("role")
    return str(msg_type or "")


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, list):
        return " ".join(str(item) for item in content)
    return str(content or "")


def _tool_name(message: Any) -> str:
    name = getattr(message, "name", None)
    if name is None and isinstance(message, dict):
        name = message.get("name")
    return str(name or "tool")


def _tool_result_preview(message: Any) -> str:
    content = " ".join(_message_content(message).split())
    if not content:
        return "(empty result)"
    line_count = len(_message_content(message).splitlines())
    if _tool_name(message) == "read_file":
        return f"{line_count} lines"
    if len(content) > _MAX_PREVIEW_CHARS:
        content = content[: _MAX_PREVIEW_CHARS - 3] + "..."
    return content
