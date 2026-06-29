from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from agent.config import Settings
from agent.tools.react_evidence import gather_evidence


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
    )


def test_gather_evidence_renders_findings_and_investigation(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def invoke(self, payload, config):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "grep_repo",
                                "args": {"pattern": "imx219"},
                                "id": "call-1",
                            }
                        ],
                    ),
                    ToolMessage(
                        content="board.dts:1: compatible = \"sony,imx219\"",
                        name="grep_repo",
                        tool_call_id="call-1",
                    ),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "read_file",
                                "args": {"path": "board.dts", "start": 1, "end": 3},
                                "id": "call-2",
                            }
                        ],
                    ),
                    ToolMessage(
                        content="1: camera@10 {\n2: status = \"disabled\";\n3: };",
                        name="read_file",
                        tool_call_id="call-2",
                    ),
                    AIMessage(content="The imx219 node is disabled in board.dts."),
                ]
            }

    def fake_create_agent(model, tools, system_prompt):
        assert len(tools) == 2
        assert "Do not produce a diff" in system_prompt
        return FakeAgent()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeModel)
    monkeypatch.setattr("langchain.agents.create_agent", fake_create_agent)

    markdown = gather_evidence(repo, "camera failed", ["jetson-customize-camera"], make_settings(tmp_path))

    assert "## Findings" in markdown
    assert "The imx219 node is disabled in board.dts." in markdown
    assert "## Investigation" in markdown
    assert "grep_repo(pattern='imx219')" in markdown
    assert "read_file(path='board.dts', start=1, end=3) -> 3 lines" in markdown


def test_gather_evidence_recursion_error_returns_non_convergence_note(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def invoke(self, payload, config):
            raise GraphRecursionError("recursion limit")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeModel)
    monkeypatch.setattr("langchain.agents.create_agent", lambda *args, **kwargs: FakeAgent())

    markdown = gather_evidence(repo, "camera failed", [], make_settings(tmp_path), recursion_limit=1)

    assert "## Findings" in markdown
    assert "(investigation did not converge within 1 rounds)" in markdown
    assert "## Investigation (0 rounds)" in markdown
