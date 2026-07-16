from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphRecursionError

from agent.config import Settings
from agent.tools.deep_patch_agent import (
    build_deep_patch_agent,
    run_deep_patch_agent,
    stage_edit_file,
)
from agent.tools.edit_agent_tools import editable_repo


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
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    return staging


def test_stage_edit_file_edits_existing_staging_file_and_rejects_escape(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)
    outside = tmp_path / "outside.dts"
    outside.write_text('status = "disabled";\n', encoding="utf-8")

    with editable_repo(staging):
        result = stage_edit_file.invoke(
            {
                "file_path": "/board.dts",
                "old_string": 'status = "disabled";',
                "new_string": 'status = "okay";',
            }
        )
        escaped = stage_edit_file.invoke(
            {
                "file_path": "../outside.dts",
                "old_string": 'status = "disabled";',
                "new_string": 'status = "okay";',
            }
        )

    assert result == "(ok: replaced 1)"
    assert "error" in escaped
    assert (staging / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'
    assert outside.read_text(encoding="utf-8") == 'status = "disabled";\n'


def test_build_deep_patch_agent_uses_stable_harness_api(tmp_path: Path) -> None:
    staging = make_staging(tmp_path)

    agent = build_deep_patch_agent(staging, make_settings(tmp_path))

    assert type(agent).__name__ == "CompiledStateGraph"
    assert "model" in agent.get_graph().nodes
    assert "tools" in agent.get_graph().nodes


def test_deep_patch_agent_denies_builtin_file_creation(tmp_path: Path, monkeypatch) -> None:
    staging = make_staging(tmp_path)

    class ScriptedModel(BaseChatModel):
        calls: int = 0

        @property
        def _llm_type(self) -> str:
            return "scripted-test-model"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"file_path": "/created.txt", "content": "blocked"},
                            "id": "write-1",
                            "type": "tool_call",
                        }
                    ],
                )
            else:
                message = AIMessage(content="No file was created.")
            return ChatResult(generations=[ChatGeneration(message=message)])

    model = ScriptedModel()
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda **kwargs: model)
    agent = build_deep_patch_agent(staging, make_settings(tmp_path))

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Create a file."}]},
        config={"recursion_limit": 10},
    )

    assert not (staging / "created.txt").exists()
    tool_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert tool_results
    assert "permission" in str(tool_results[0].content).lower()


def test_run_deep_patch_agent_fake_harness_edits_staging(
    tmp_path: Path, monkeypatch
) -> None:
    staging = make_staging(tmp_path)
    captured: dict[str, object] = {}

    class FakeAgent:
        def stream(self, payload, config, stream_mode):
            captured["payload"] = payload
            captured["config"] = config
            captured["stream_mode"] = stream_mode
            stage_edit_file.invoke(
                {
                    "file_path": "/board.dts",
                    "old_string": 'status = "disabled";',
                    "new_string": 'status = "okay";',
                }
            )
            yield {"messages": []}

    monkeypatch.setattr(
        "agent.tools.deep_patch_agent.build_deep_patch_agent",
        lambda *args, **kwargs: FakeAgent(),
    )

    run_deep_patch_agent(
        staging,
        "camera failed",
        "camera skill",
        "MIC-741 case",
        "prior feedback",
        make_settings(tmp_path),
        recursion_limit=17,
    )

    assert (staging / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'
    assert captured["config"]["recursion_limit"] == 17
    prompt = captured["payload"]["messages"][0]["content"]
    assert "camera skill" in prompt
    assert "MIC-741 case" in prompt
    assert "prior feedback" in prompt


def test_run_deep_patch_agent_recursion_limit_keeps_staging_edits(
    tmp_path: Path, monkeypatch
) -> None:
    staging = make_staging(tmp_path)

    class FakeAgent:
        def stream(self, payload, config, stream_mode):
            stage_edit_file.invoke(
                {
                    "file_path": "/board.dts",
                    "old_string": 'status = "disabled";',
                    "new_string": 'status = "okay";',
                }
            )
            raise GraphRecursionError("limit")

    monkeypatch.setattr(
        "agent.tools.deep_patch_agent.build_deep_patch_agent",
        lambda *args, **kwargs: FakeAgent(),
    )

    run_deep_patch_agent(
        staging,
        "camera failed",
        "",
        "",
        "",
        make_settings(tmp_path),
        recursion_limit=1,
    )

    assert (staging / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'
