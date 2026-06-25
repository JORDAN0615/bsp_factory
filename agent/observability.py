from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any

from dotenv import load_dotenv


load_dotenv()

_client = None


def enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _get_client():
    global _client
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse()
    return _client


@contextmanager
def run_span(run_id: str, issue: str):
    if not enabled():
        yield None
        return
    client = _get_client()
    trace_id = client.create_trace_id(seed=run_id)
    issue_summary = (issue or "").splitlines()[0][:180] if issue else ""
    metadata = {
        "issue": issue_summary,
        "session_id": run_id,
        "tags": ["bsp-agent"],
    }
    with client.start_as_current_observation(
        trace_context={"trace_id": trace_id},
        name=f"run:{run_id}",
        as_type="span",
        metadata=metadata,
    ) as span:
        span.update(name=f"run:{run_id}")
        yield span


class _NullGen:
    def update(self, *args: Any, **kwargs: Any) -> None:
        pass


@contextmanager
def generation(model: str, messages, name: str = "chat_completion"):
    if not enabled():
        yield _NullGen()
        return
    client = _get_client()
    with client.start_as_current_observation(
        name=name,
        as_type="generation",
        model=model,
        input=messages,
    ) as gen:
        yield gen


def flush() -> None:
    if enabled():
        _get_client().flush()


def langchain_handler():
    if not enabled():
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()
