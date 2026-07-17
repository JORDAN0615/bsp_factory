from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.config import Settings
from agent.graph import route_after_knowledge_retrieval, route_after_planner
from agent.tools.planner_agent import build_planner_agent, run_planner_agent


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "LLM_API_KEY": "EMPTY",
        "LLM_MODEL": "test",
        "PLANNER_LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "PLANNER_LLM_API_KEY": "EMPTY",
        "PLANNER_LLM_MODEL": "cloud-test",
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
    }
    values.update(overrides)
    return Settings(**values)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    return repo


def test_route_after_knowledge_retrieval_selects_planner(tmp_path: Path) -> None:
    deep_only = make_settings(tmp_path, DEEP_AGENT_ENABLED=True, PLANNER_ENABLED=False)
    with_planner = make_settings(tmp_path, DEEP_AGENT_ENABLED=True, PLANNER_ENABLED=True)
    legacy = make_settings(tmp_path, DEEP_AGENT_ENABLED=False, PLANNER_ENABLED=True)

    assert route_after_knowledge_retrieval({"settings": deep_only}) == "deep_patch_agent"
    assert route_after_knowledge_retrieval({"settings": with_planner}) == "deep_planner"
    # Planner only applies on the deep path; legacy ignores it.
    assert route_after_knowledge_retrieval({"settings": legacy}) == "inspect_repo"


def test_planner_is_read_only(tmp_path: Path) -> None:
    agent = build_planner_agent(make_repo(tmp_path), make_settings(tmp_path))
    # The planner has skill tools but no staging edit tool.
    tool_names = {t.name for t in agent.get_graph().nodes["tools"].data.tools_by_name.values()} \
        if "tools" in agent.get_graph().nodes else set()
    assert "stage_edit_file" not in tool_names


def test_run_planner_agent_returns_final_guide(tmp_path: Path, monkeypatch) -> None:
    guide_json = '```json\n{"root_cause":"x","strategy":"y","changes":[]}\n```'

    class ScriptedModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "scripted"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=guide_json))])

    model = ScriptedModel()
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda **kwargs: model)

    guide = run_planner_agent(
        make_repo(tmp_path), "camera failed", "MIC-741 case", "", make_settings(tmp_path),
        recursion_limit=5,
    )
    assert '"root_cause"' in guide


def test_route_after_planner() -> None:
    class S:
        failure_reason = None

    class SFail:
        failure_reason = "planner down"

    assert route_after_planner({"state": S()}) == "deep_patch_agent"
    assert route_after_planner({"state": SFail()}) == "human_review"
