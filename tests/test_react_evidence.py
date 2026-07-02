from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from agent.config import Settings
from agent.tools.react_evidence import gather_evidence, render_evidence_md


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
        def stream(self, payload, config, stream_mode):
            messages = [
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
            yield {"messages": messages}

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
    assert "## Source excerpts" in markdown
    assert '1: camera@10 {\n2: status = "disabled";\n3: };' in markdown


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
        def stream(self, payload, config, stream_mode):
            yield {
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
                ]
            }
            raise GraphRecursionError("recursion limit")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeModel)
    monkeypatch.setattr("langchain.agents.create_agent", lambda *args, **kwargs: FakeAgent())

    markdown = gather_evidence(repo, "camera failed", [], make_settings(tmp_path), recursion_limit=1)

    assert "## Findings" in markdown
    assert "(did not fully converge within 1 rounds; partial evidence below)" in markdown
    assert "## Investigation (1 rounds)" in markdown
    assert "grep_repo(pattern='imx219')" in markdown
    assert "board.dts:1: compatible" in markdown
    assert "no tool calls recorded" not in markdown


def test_render_evidence_md_includes_verbatim_read_file_source_excerpts() -> None:
    content = (
        "1: reg = <0x10>;\n"
        "2: reset-gpios = <&gpio 1 0>;\n"
        "3: avdd-reg = <&cam_avdd>;\n"
        "4: iovdd-reg = <&cam_iovdd>;"
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": "kernel/camera.dtsi", "start": 1, "end": 4},
                    "id": "call-1",
                }
            ],
        ),
        ToolMessage(content=content, name="read_file", tool_call_id="call-1"),
        AIMessage(content="Found the camera node."),
    ]

    markdown = render_evidence_md(messages)

    assert "## Source excerpts" in markdown
    assert "### read_file kernel/camera.dtsi (lines 1-4)" in markdown
    assert "1: reg = <0x10>;" in markdown
    assert "2: reset-gpios = <&gpio 1 0>;" in markdown
    assert "3: avdd-reg = <&cam_avdd>;" in markdown
    assert "4: iovdd-reg = <&cam_iovdd>;" in markdown
    assert "read_file(path='kernel/camera.dtsi', start=1, end=4) -> 4 lines" in markdown


def test_render_evidence_md_includes_full_grep_source_excerpt() -> None:
    grep_content = (
        "drivers/media/i2c/imx219.c:10:static const struct of_device_id imx219_of_match[]\n"
        "arch/arm64/boot/dts/nvidia/board.dts:42:compatible = \"sony,imx219\""
    )
    messages = [
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
        ToolMessage(content=grep_content, name="grep_repo", tool_call_id="call-1"),
        AIMessage(content="Found imx219 references."),
    ]

    markdown = render_evidence_md(messages)

    assert "### grep_repo imx219" in markdown
    assert "drivers/media/i2c/imx219.c:10:static const struct of_device_id" in markdown
    assert 'arch/arm64/boot/dts/nvidia/board.dts:42:compatible = "sony,imx219"' in markdown


def test_render_evidence_md_deduplicates_identical_source_excerpts() -> None:
    call = {
        "name": "read_file",
        "args": {"path": "board.dts", "start": 1, "end": 2},
        "id": "call-1",
    }
    content = '1: camera@10 {\n2: status = "disabled";'
    messages = [
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content=content, name="read_file", tool_call_id="call-1"),
        AIMessage(content="", tool_calls=[{**call, "id": "call-2"}]),
        ToolMessage(content=content, name="read_file", tool_call_id="call-2"),
        AIMessage(content="Found duplicate reads."),
    ]

    markdown = render_evidence_md(messages)

    assert markdown.count("### read_file board.dts (lines 1-2)") == 1
    assert markdown.count('1: camera@10 {\n2: status = "disabled";') == 1
