from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.config import Settings
from agent.graph import route_after_classify_error, route_after_planner
from agent.tools.planner_agent import build_planner_agent, run_planner_agent


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "LLM_API_KEY": "EMPTY",
        "LLM_MODEL": "test",
        "PLANNER_LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "PLANNER_LLM_API_KEY": "EMPTY",
        "PLANNER_LLM_MODEL": "cloud-test",
        "WEB_FETCH_ENABLED": False,
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
    }
    values.update(overrides)
    return Settings(**values)


def make_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_route_after_classification_selects_planner(tmp_path: Path) -> None:
    deep_only = make_settings(tmp_path, DEEP_AGENT_ENABLED=True, PLANNER_ENABLED=False)
    with_planner = make_settings(tmp_path, DEEP_AGENT_ENABLED=True, PLANNER_ENABLED=True)
    legacy = make_settings(tmp_path, DEEP_AGENT_ENABLED=False, PLANNER_ENABLED=True)

    assert route_after_classify_error({"settings": deep_only}) == "deep_patch_agent"
    assert route_after_classify_error({"settings": with_planner}) == "deep_planner"
    # Planner only applies on the deep path; legacy ignores it.
    assert route_after_classify_error({"settings": legacy}) == "select_skills"


def test_planner_has_rag_tool_but_no_edit_tool(tmp_path: Path) -> None:
    agent = build_planner_agent(make_repo(tmp_path), make_settings(tmp_path))
    tool_names = {t.name for t in agent.get_graph().nodes["tools"].data.tools_by_name.values()} \
        if "tools" in agent.get_graph().nodes else set()
    # RAG is an on-demand tool inside the planner; editing is not.
    assert "search_bsp_knowledge" in tool_names
    assert "search_mic741_knowledge" not in tool_names
    assert "search_technical_docs" not in tool_names
    assert "fetch_web_page" not in tool_names
    assert "stage_edit_file" not in tool_names


def test_planner_adds_web_fetch_only_when_enabled(tmp_path: Path) -> None:
    agent = build_planner_agent(
        make_repo(tmp_path), make_settings(tmp_path, WEB_FETCH_ENABLED=True)
    )
    tool_names = (
        {tool.name for tool in agent.get_graph().nodes["tools"].data.tools_by_name.values()}
        if "tools" in agent.get_graph().nodes
        else set()
    )

    assert "fetch_web_page" in tool_names


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
        make_repo(tmp_path), "camera failed", "", make_settings(tmp_path),
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
