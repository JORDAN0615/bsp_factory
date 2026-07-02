from pathlib import Path

from langgraph.errors import GraphRecursionError

from agent.config import Settings
from agent.tools.patch_agent import run_patch_agent


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        LLM_BASE_URL="http://127.0.0.1:9/v1",
        LLM_API_KEY="EMPTY",
        LLM_MODEL="test",
        runs_dir=tmp_path / "runs",
        skills_dir=Path("skills"),
        validation_dir=Path("tests/validation"),
    )


def make_staging(tmp_path: Path) -> Path:
    repo = tmp_path / "staging"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    return repo


def test_run_patch_agent_fake_agent_edits_staging(tmp_path: Path, monkeypatch) -> None:
    staging = make_staging(tmp_path)

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def __init__(self, tools):
            self.tools = {tool.name: tool for tool in tools}

        def stream(self, payload, config, stream_mode):
            self.tools["edit_file"].invoke(
                {
                    "path": "board.dts",
                    "search": 'status = "disabled";',
                    "replace": 'status = "okay";',
                }
            )
            yield {"messages": []}

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeModel)
    monkeypatch.setattr(
        "langchain.agents.create_agent",
        lambda model, tools, system_prompt: FakeAgent(tools),
    )

    run_patch_agent(staging, "camera failed", "", "", "", make_settings(tmp_path))

    assert (staging / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'


def test_run_patch_agent_recursion_error_keeps_partial_edits(tmp_path: Path, monkeypatch) -> None:
    staging = make_staging(tmp_path)

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def __init__(self, tools):
            self.tools = {tool.name: tool for tool in tools}

        def stream(self, payload, config, stream_mode):
            self.tools["edit_file"].invoke(
                {
                    "path": "board.dts",
                    "search": 'status = "disabled";',
                    "replace": 'status = "okay";',
                }
            )
            raise GraphRecursionError("limit")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeModel)
    monkeypatch.setattr(
        "langchain.agents.create_agent",
        lambda model, tools, system_prompt: FakeAgent(tools),
    )

    run_patch_agent(staging, "camera failed", "", "", "", make_settings(tmp_path), recursion_limit=1)

    assert (staging / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'
