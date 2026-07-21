from __future__ import annotations

import json
import re
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


def transient_llm_errors() -> tuple[type[BaseException], ...]:
    """Errors where retrying the same request later can succeed.

    Covers the urllib choke point (LLMError) plus the openai SDK exceptions
    raised by the agentic ChatOpenAI nodes. openai ships with langchain-openai,
    so the import guard only matters in environments without the agentic extras.
    """
    errors: tuple[type[BaseException], ...] = (LLMError,)
    try:
        import openai
    except ImportError:
        return errors
    return errors + (
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
    )


def chat_completion(
    config: LLMConfig,
    messages: list[dict[str, str]],
    timeout_sec: int = 60,
    name: str = "chat_completion",
    temperature: float = 0.1,
) -> str:
    url = config.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
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
    """Recover the JSON payload from a model reply that is not pure JSON.

    Never assume the JSON starts at character 0. Reasoning models emit a
    `<think>…</think>` block first, and ordinary ones often add a sentence of
    preamble; either made every `json.loads` call site fail at "line 1 column 1",
    which silently degraded the Code Review Agent to `needs_human` on every run.
    So: drop reasoning blocks, take a fenced block wherever it appears, and
    finally fall back to the outermost brace/bracket span.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # An unterminated reasoning block (truncated output) would otherwise swallow
    # the whole reply; drop from the opening tag to the first fence instead.
    cleaned = re.sub(r"<think>.*?(?=```|\{|\[)", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    fenced = re.search(r"```(?:json)?\s*\n(.*?)\n?```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    # Prose before or after bare JSON: keep the outermost object/array.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if 0 <= start < end:
            return cleaned[start : end + 1].strip()
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
