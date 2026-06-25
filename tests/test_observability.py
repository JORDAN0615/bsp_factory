import json
from contextlib import contextmanager

from agent import observability
from agent.tools.llm_tools import LLMConfig, chat_completion


def test_observability_disabled_does_not_construct_client(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    def fail_get_client():
        raise AssertionError("Langfuse client should not be constructed when disabled")

    monkeypatch.setattr(observability, "_get_client", fail_get_client)

    assert observability.enabled() is False
    with observability.run_span("run-1", "issue") as span:
        assert span is None
    with observability.generation("model", [{"role": "user", "content": "hi"}]) as gen:
        gen.update(output="ok")
    assert observability.langchain_handler() is None
    observability.flush()


def test_chat_completion_tracing_disabled_returns_normally(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    @contextmanager
    def fake_generation(model, messages, name="chat_completion"):
        class Gen:
            def __init__(self):
                self.updated = False

            def update(self, *args, **kwargs):
                self.updated = True

        gen = Gen()
        yield gen
        assert gen.updated is True

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "fixed"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            ).encode("utf-8")

    monkeypatch.setattr(observability, "generation", fake_generation)
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    result = chat_completion(
        LLMConfig(base_url="http://llm.example/v1", api_key="test", model="test-model"),
        [{"role": "user", "content": "hello"}],
    )

    assert result == "fixed"
