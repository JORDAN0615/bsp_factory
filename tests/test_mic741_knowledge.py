from pathlib import Path

import pytest

from agent.config import Settings
from agent.graph import inspect_repo_node, retrieve_mic741_knowledge_node
from agent.state import BSPAgentState, RepairAttempt
from agent.tools.mic741_knowledge import (
    KnowledgeDBError,
    LLMError,
    _build_rerank_messages,
    _normalize_case_key,
    _rerank_with_llm,
    _select_relevant_hunks,
    _split_hunk_units,
    parse_mic741_cases,
    query_mic741_knowledge,
    render_knowledge_matches,
)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "LLM_API_KEY": "EMPTY",
        "LLM_MODEL": "test",
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
        "MIC741_KNOWLEDGE_ENABLED": False,
        "MIC741_KNOWLEDGE_DB_URL": "",
        "MIC741_KNOWLEDGE_SOURCE_DIR": tmp_path / "MIC-741_KnowledgeBase",
    }
    values.update(overrides)
    return Settings(**values)


def make_source(tmp_path: Path) -> Path:
    source = tmp_path / "MIC-741_KnowledgeBase"
    issue_dir = source / "01_Issues"
    case_dir = source / "02_Original_Code" / "RE-07_camera-sipl-genericize"
    before = case_dir / "before" / "source" / "config"
    after = case_dir / "after" / "source" / "config"
    issue_dir.mkdir(parents=True)
    before.mkdir(parents=True)
    after.mkdir(parents=True)
    (issue_dir / "RE-07_camera-sipl-genericize.md").write_text(
        "# RE-07 - Genericize Camera SIPL download + support v38.4.0\n\n"
        "| 欄位 | 內容 |\n"
        "|---|---|\n"
        "| 反推來源 commit | `4e2f1bc` |\n"
        "| 主要檔案 | `source/config/task_download_after.sh` |\n\n"
        "## 問題 / 目標\n\n"
        "Camera SIPL download is hardcoded.\n\n"
        "## 解法（實際 commit 做法）\n\n"
        "- Parameterize Camera SIPL URL and MD5 for v38.4.0.\n",
        encoding="utf-8",
    )
    (before / "task_download_after.sh").write_text(
        'TARGET_L4T_VERSION="38.2.1"\nURL_SIPL="old"\n',
        encoding="utf-8",
    )
    (after / "task_download_after.sh").write_text(
        'TARGET_L4T_VERSION="${TARGET_L4T_VERSION:-38.4.0}"\nURL_SIPL="${URL_SIPL:-new}"\n',
        encoding="utf-8",
    )
    (case_dir / "4e2f1bc.patch").write_text(
        "diff --git a/source/config/task_download_after.sh "
        "b/source/config/task_download_after.sh\n"
        "--- a/source/config/task_download_after.sh\n"
        "+++ b/source/config/task_download_after.sh\n"
        '@@ -1 +1 @@\n-TARGET_L4T_VERSION="38.2.1"\n'
        '+TARGET_L4T_VERSION="${TARGET_L4T_VERSION:-38.4.0}"\n',
        encoding="utf-8",
    )
    return source


def test_parse_mic741_cases_preserves_issue_fix_and_code(tmp_path: Path) -> None:
    source = make_source(tmp_path)

    cases = parse_mic741_cases(source)

    assert len(cases) == 1
    case = cases[0]
    assert case.case_key == "RE-07"
    assert case.subsystem == "camera"
    assert case.commit_sha == "4e2f1bc"
    assert "Parameterize Camera SIPL" in case.solution_summary
    roles = {artifact.file_role for artifact in case.files}
    assert {"issue", "before", "after", "patch"} <= roles
    after_file = next(
        artifact
        for artifact in case.files
        if artifact.file_role == "after"
        and artifact.repo_relative_path == "source/config/task_download_after.sh"
    )
    assert "TARGET_L4T_VERSION" in after_file.content


def test_render_knowledge_matches_keeps_case_boundary_and_patch() -> None:
    markdown = render_knowledge_matches(
        [
            {
                "case_key": "RE-07",
                "title": "Camera SIPL",
                "subsystem": "camera",
                "commit_sha": "4e2f1bc",
                "matches": ["Camera SIPL download is hardcoded"],
                "issue_markdown": "# RE-07\n\nCamera SIPL download is hardcoded",
                "solution_summary": "Parameterize URL and MD5.",
                "repair_rule": "For similar camera issues, parameterize SIPL download.",
                "patch_excerpt": "--- a/file\n+++ b/file\n",
            }
        ]
    )

    assert "## MIC-741 Knowledge Matches" in markdown
    assert "### 1. RE-07 - Camera SIPL" in markdown
    assert "Human fix:" in markdown
    assert "Parameterize URL and MD5." in markdown
    assert "```diff\n--- a/file" in markdown


def test_query_requires_db_url(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, MIC741_KNOWLEDGE_DB_URL="")

    with pytest.raises(KnowledgeDBError, match="MIC741_KNOWLEDGE_DB_URL"):
        query_mic741_knowledge("camera sipl", [], settings)


def test_retrieve_mic741_knowledge_node_writes_artifact(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        issue="Camera SIPL download is hardcoded",
        attempts=[RepairAttempt(attempt_no=1, bug_type="camera")],
    )
    settings = make_settings(
        tmp_path,
        MIC741_KNOWLEDGE_ENABLED=True,
        MIC741_KNOWLEDGE_DB_URL="postgresql://example",
        MIC741_KNOWLEDGE_QUERY_LIMIT=10,
    )

    def fake_query(issue, logs, settings, *, subsystem=None, limit=None, debug_dir=None):
        assert issue == "Camera SIPL download is hardcoded"
        assert logs == ["camera log"]
        # bug_type is classify vocabulary and must NOT be used as a subsystem
        # filter (it never matches the DB subsystem column).
        assert subsystem is None
        assert limit == 10
        assert debug_dir == Path(state.run_dir) / "attempts" / "001" / "debug"
        return "## MIC-741 Knowledge Matches\n\n### RE-07\nHistorical fix."

    monkeypatch.setattr("agent.tools.mic741_knowledge.query_mic741_knowledge", fake_query)

    result = retrieve_mic741_knowledge_node(
        {"state": state, "settings": settings, "logs_text": ["camera log"]}
    )

    assert result["knowledge_context"].startswith("## MIC-741 Knowledge Matches")
    assert state.stage == "retrieve_mic741_knowledge"
    artifact = Path(state.run_dir) / "attempts" / "001" / "mic741_knowledge.md"
    assert "Historical fix." in artifact.read_text(encoding="utf-8")


def test_inspect_repo_prepends_existing_knowledge_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "task_download_after.sh").write_text("camera sipl\n", encoding="utf-8")
    state = BSPAgentState(
        run_id="run123",
        repo_path=str(repo),
        run_dir=str(tmp_path / "runs" / "run123"),
        issue="Camera SIPL download is hardcoded",
        attempts=[RepairAttempt(attempt_no=1, bug_type="camera")],
    )
    settings = make_settings(tmp_path)

    result = inspect_repo_node(
        {
            "state": state,
            "settings": settings,
            "knowledge_context": "## MIC-741 Knowledge Matches\n\n### RE-07\nHistorical fix.",
        }
    )

    assert result["repo_inspection"].startswith("## MIC-741 Knowledge Matches")
    artifact = Path(state.run_dir) / "attempts" / "001" / "repo_inspection.md"
    assert "Historical fix." in artifact.read_text(encoding="utf-8")


def rerank_rows() -> list[dict]:
    return [
        {
            "case_key": "RE-17",
            "title": "Switch Camera SIPL to L4T r39.2.0",
            "subsystem": "camera",
            "solution_summary": "Switch Camera SIPL to L4T r39.2.0.",
            "main_files": ["source/config/task_download_after.sh"],
            "matches": ["raw match should not appear"],
        },
        {
            "case_key": "RE-07",
            "title": "Genericize Camera SIPL download",
            "subsystem": "camera",
            "solution_summary": "Parameterize Camera SIPL and support v38.4.0.",
            "main_files": ["source/config/task_download_after.sh"],
            "matches": ["raw match should not appear"],
        },
        {
            "case_key": "RE-02",
            "title": "Apply MIC-741 board config",
            "subsystem": "can",
            "solution_summary": "Apply board flash config.",
            "main_files": ["source/config/config.mk"],
            "matches": ["raw match should not appear"],
        },
    ]


def test_rerank_happy_path_orders_picked_cases(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, MIC741_RERANK_TOP_K=2)
    captured = {}

    def fake_chat(config, messages, timeout_sec, name, temperature=0.1):
        captured["name"] = name
        captured["temperature"] = temperature
        return '{"ranked":[{"case_key":"RE-07"},{"case_key":"RE-17"}]}'

    monkeypatch.setattr("agent.tools.mic741_knowledge.chat_completion", fake_chat)

    result = _rerank_with_llm("camera sipl v38.4.0", [], rerank_rows(), settings)

    assert [row["case_key"] for row in result] == ["RE-07", "RE-17"]
    assert captured == {"name": "mic741_rerank", "temperature": 0}


def test_rerank_returns_fewer_than_top_k(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, MIC741_RERANK_TOP_K=3)
    monkeypatch.setattr(
        "agent.tools.mic741_knowledge.chat_completion",
        lambda *args, **kwargs: '{"ranked":[{"case_key":"RE-07"}]}',
    )

    result = _rerank_with_llm("camera sipl v38.4.0", [], rerank_rows(), settings)

    assert [row["case_key"] for row in result] == ["RE-07"]


def test_normalize_case_key_accepts_full_stem_and_rejects_hallucination() -> None:
    valid = {"RE-07", "ISSUE-G42005"}

    assert _normalize_case_key("RE-07_camera-sipl-genericize", valid) == "RE-07"
    assert _normalize_case_key("ISSUE-G42005_GPU-nvpmodel", valid) == "ISSUE-G42005"
    assert _normalize_case_key("RE-99", valid) == ""


def test_rerank_drops_hallucinated_keys(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, MIC741_RERANK_TOP_K=3)
    monkeypatch.setattr(
        "agent.tools.mic741_knowledge.chat_completion",
        lambda *args, **kwargs: '{"ranked":[{"case_key":"RE-99"},{"case_key":"RE-07"}]}',
    )

    result = _rerank_with_llm("camera sipl v38.4.0", [], rerank_rows(), settings)

    assert [row["case_key"] for row in result] == ["RE-07"]


def test_rerank_llm_error_fails_open_and_writes_artifact(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, MIC741_RERANK_TOP_K=2)

    def boom(*args, **kwargs):
        raise LLMError("timeout")

    monkeypatch.setattr("agent.tools.mic741_knowledge.chat_completion", boom)

    result = _rerank_with_llm(
        "camera sipl v38.4.0",
        [],
        rerank_rows(),
        settings,
        debug_dir=tmp_path,
    )

    assert [row["case_key"] for row in result] == ["RE-17", "RE-07"]
    artifact = tmp_path / "mic741_rerank.json"
    assert '"fallback": true' in artifact.read_text(encoding="utf-8")


def test_rerank_invalid_json_fails_open(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, MIC741_RERANK_TOP_K=2)
    monkeypatch.setattr(
        "agent.tools.mic741_knowledge.chat_completion",
        lambda *args, **kwargs: "not json",
    )

    result = _rerank_with_llm("camera sipl v38.4.0", [], rerank_rows(), settings)

    assert [row["case_key"] for row in result] == ["RE-17", "RE-07"]


def test_query_skips_rerank_when_rows_do_not_exceed_top_k(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(
        tmp_path,
        MIC741_KNOWLEDGE_DB_URL="postgresql://example",
        MIC741_RERANK_ENABLED=True,
        MIC741_RERANK_TOP_K=3,
    )
    monkeypatch.setattr("agent.tools.mic741_knowledge._query_rows", lambda *args, **kwargs: rerank_rows()[:2])

    def fail_chat(*args, **kwargs):
        raise AssertionError("chat_completion should not be called")

    monkeypatch.setattr("agent.tools.mic741_knowledge.chat_completion", fail_chat)

    markdown = query_mic741_knowledge("camera sipl", [], settings)

    assert "RE-17" in markdown
    assert "RE-07" in markdown


def test_build_rerank_messages_sorted_and_omits_matches() -> None:
    messages = _build_rerank_messages("camera sipl", ["log line"], rerank_rows(), top_k=3)
    user = messages[1]["content"]

    assert user.index("[RE-02]") < user.index("[RE-07]") < user.index("[RE-17]")
    assert "raw match should not appear" not in user
    assert "source/config/task_download_after.sh" in user


def multi_hunk_patch() -> str:
    return (
        "commit abc\n"
        "Author: Test\n\n"
        "diff --git a/source/config/a.dtsi b/source/config/a.dtsi\n"
        "index 111..222 100644\n"
        "--- a/source/config/a.dtsi\n"
        "+++ b/source/config/a.dtsi\n"
        "@@ -10,3 +10,3 @@\n"
        "-old pinmux_a\n"
        "+new pinmux_a\n"
        "@@ -20,3 +20,3 @@\n"
        "-old unrelated\n"
        "+new unrelated\n"
        "diff --git a/source/config/b.dtsi b/source/config/b.dtsi\n"
        "index 333..444 100644\n"
        "--- a/source/config/b.dtsi\n"
        "+++ b/source/config/b.dtsi\n"
        "@@ -30,3 +30,3 @@\n"
        "-old gpio_b\n"
        "+new gpio_b\n"
    )


def test_split_hunk_units_preserves_headers_and_drops_preamble() -> None:
    units = _split_hunk_units(multi_hunk_patch())

    assert len(units) == 3
    assert all(sum(1 for line in unit.splitlines() if line.startswith("@@")) == 1 for unit in units)
    assert all("--- " in unit and "+++ " in unit for unit in units)
    assert all("commit abc" not in unit and "Author:" not in unit for unit in units)
    assert units[0].startswith("diff --git")


def test_select_relevant_hunks_includes_all_when_budget_allows_re16_regression() -> None:
    patch = (
        multi_hunk_patch()
        + "diff --git a/source/config/c.dtsi b/source/config/c.dtsi\n"
        + "--- a/source/config/c.dtsi\n"
        + "+++ b/source/config/c.dtsi\n"
        + "@@ -2090,25 +2093,26 @@\n"
        + "-old i2c3\n"
        + "+new i2c3\n"
    )

    selected = _select_relevant_hunks(patch, "fix i2c3 pinmux", [], budget_chars=20000)

    assert "@@ -2090" in selected
    assert "omitted" not in selected
    assert len(_split_hunk_units(selected)) == 4


def test_select_relevant_hunks_drops_whole_units_with_marker() -> None:
    selected = _select_relevant_hunks(
        multi_hunk_patch(),
        "pinmux_a",
        [],
        budget_chars=260,
    )

    assert "pinmux_a" in selected
    assert "omitted" in selected
    assert sum(1 for line in selected.splitlines() if line.startswith("@@")) == 1
    assert selected.rstrip().endswith("omitted)")


def test_select_relevant_hunks_keeps_anchor_hunk_when_only_one_fits() -> None:
    selected = _select_relevant_hunks(
        multi_hunk_patch(),
        "gpio_b failure",
        [],
        budget_chars=260,
    )

    assert "gpio_b" in selected
    assert "pinmux_a" not in selected


def test_select_relevant_hunks_keeps_one_large_unit_even_over_budget() -> None:
    patch = (
        "diff --git a/huge.dtsi b/huge.dtsi\n"
        "--- a/huge.dtsi\n"
        "+++ b/huge.dtsi\n"
        "@@ -1,3 +1,3 @@\n"
        + ("+very long line\n" * 100)
    )

    selected = _select_relevant_hunks(patch, "huge", [], budget_chars=10)

    assert "very long line" in selected
    assert "omitted" not in selected


def test_query_builds_patch_excerpt_from_full_patch_content(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(
        tmp_path,
        MIC741_KNOWLEDGE_DB_URL="postgresql://example",
        MIC741_RERANK_ENABLED=False,
        MIC741_KNOWLEDGE_HUNK_BUDGET_CHARS=20000,
    )
    row = {
        "case_key": "RE-16",
        "title": "Pinmux rsvd",
        "subsystem": "pinmux",
        "commit_sha": "d0eeee7",
        "matches": ["pinmux i2c3"],
        "issue_markdown": "# RE-16\n\npinmux",
        "solution_summary": "Restore I2C3 pinmux.",
        "repair_rule": "Restore reserved pinmux fields.",
        "patch_content": (
            "commit should be dropped\n"
            "diff --git a/pinmux.dtsi b/pinmux.dtsi\n"
            "--- a/pinmux.dtsi\n"
            "+++ b/pinmux.dtsi\n"
            "@@ -2090,25 +2093,26 @@\n"
            "-old i2c3\n"
            "+new i2c3\n"
        ),
    }
    monkeypatch.setattr("agent.tools.mic741_knowledge._query_rows", lambda *args, **kwargs: [row])

    markdown = query_mic741_knowledge("fix i2c3 pinmux", [], settings)

    assert "@@ -2090" in markdown
    assert "commit should be dropped" not in markdown
