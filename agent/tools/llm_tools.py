from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from agent import observability


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


class LLMError(RuntimeError):
    pass


def chat_completion(
    config: LLMConfig,
    messages: list[dict[str, str]],
    timeout_sec: int = 60,
    name: str = "chat_completion",
) -> str:
    url = config.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": config.model,
            "messages": messages,
            "temperature": 0.1,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with observability.generation(config.model, messages, name=name) as gen:
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(str(exc)) from exc
        try:
            content = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response: {data}") from exc
        usage = data.get("usage") or {}
        gen.update(
            output=content,
            usage_details={
                "input": usage.get("prompt_tokens"),
                "output": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            },
        )
        return content


def strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def extract_diff_or_no_patch(text: str) -> tuple[str, str | None]:
    cleaned = text.strip()
    if "```" in cleaned:
        # The LLM may split one patch into several fenced diff blocks; collect
        # them all so later files are not silently dropped.
        found: list[str] = []
        for index, block in enumerate(cleaned.split("```")):
            if index % 2 == 0:
                continue
            candidate = block
            lines = candidate.splitlines()
            if lines and lines[0].strip().lower() in {"diff", "patch"}:
                candidate = "\n".join(lines[1:])
            if (
                "diff --git " in candidate
                or candidate.strip().startswith("--- ")
                or candidate.strip().startswith("NO_PATCH")
            ):
                found.append(candidate.strip())
        diff_blocks = [block for block in found if not block.startswith("NO_PATCH")]
        if diff_blocks:
            cleaned = "\n".join(diff_blocks)
        elif found:
            cleaned = found[0]
    if not cleaned.startswith("NO_PATCH"):
        diff_start = cleaned.find("diff --git ")
        if diff_start == -1:
            diff_start = cleaned.find("--- a/")
        if diff_start == -1:
            diff_start = cleaned.find("--- ")
        if diff_start > 0:
            cleaned = cleaned[diff_start:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].rstrip()
    if cleaned.startswith("NO_PATCH"):
        reason = cleaned[len("NO_PATCH") :].strip(" :-\n") or "LLM declined to propose a patch."
        return "NO_PATCH", reason
    return cleaned, None
