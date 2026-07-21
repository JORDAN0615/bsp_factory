from pathlib import Path

from agent.config import Settings
from agent.tools.knowledge_tool import build_bsp_knowledge_tool


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "MIC741_KNOWLEDGE_ENABLED": True,
        "DOC_RETRIEVAL_ENABLED": True,
        "MIC741_KNOWLEDGE_DB_URL": "postgresql://example",
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
    }
    values.update(overrides)
    return Settings(**values)


def test_shared_tool_uses_combined_retrieval_when_both_sources_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def fake_query(issue, logs, settings, *, debug_dir=None):
        calls.append((issue, logs, settings, debug_dir))
        return "combined result"

    monkeypatch.setattr("agent.tools.doc_knowledge.query_all_knowledge", fake_query)
    tool = build_bsp_knowledge_tool(make_settings(tmp_path))

    result = tool.invoke({"query": "CAN2 pinmux"})

    assert result == "combined result"
    assert len(calls) == 1
    assert calls[0][0] == "CAN2 pinmux"
    assert calls[0][1] == []


def test_shared_tool_respects_single_source_modes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.tools.doc_knowledge.query_doc_knowledge",
        lambda *args, **kwargs: "docs only",
    )
    monkeypatch.setattr(
        "agent.tools.mic741_knowledge.query_mic741_knowledge",
        lambda *args, **kwargs: "cases only",
    )
    docs_tool = build_bsp_knowledge_tool(
        make_settings(
            tmp_path,
            MIC741_KNOWLEDGE_ENABLED=False,
            DOC_RETRIEVAL_ENABLED=True,
        )
    )
    cases_tool = build_bsp_knowledge_tool(
        make_settings(
            tmp_path,
            MIC741_KNOWLEDGE_ENABLED=True,
            DOC_RETRIEVAL_ENABLED=False,
        )
    )

    assert docs_tool.invoke({"query": "pinmux"}) == "docs only"
    assert cases_tool.invoke({"query": "camera"}) == "cases only"


def test_shared_tool_degrades_when_disabled_or_query_is_empty(tmp_path: Path) -> None:
    tool = build_bsp_knowledge_tool(
        make_settings(
            tmp_path,
            MIC741_KNOWLEDGE_ENABLED=False,
            DOC_RETRIEVAL_ENABLED=False,
        )
    )

    assert "empty" in tool.invoke({"query": "   "})
    assert "disabled" in tool.invoke({"query": "camera"})
