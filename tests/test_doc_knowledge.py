import logging
import math
from pathlib import Path

import httpx
import pytest

from agent.config import Settings
from agent.tools import reranker
from agent.tools.doc_knowledge import (
    _fts_query_text_prefix,
    query_all_knowledge,
    query_doc_knowledge,
)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "LLM_API_KEY": "EMPTY",
        "LLM_MODEL": "test",
        "runs_dir": tmp_path / "runs",
        "skills_dir": Path("skills"),
        "validation_dir": Path("tests/validation"),
        "MIC741_KNOWLEDGE_DB_URL": "postgresql://example",
        "MIC741_KNOWLEDGE_ENABLED": True,
        "DOC_RETRIEVAL_ENABLED": True,
        "RERANK_CANDIDATE_LIMIT": 100,
        "RERANK_TOP_K": 10,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def clear_reranker_cache():
    reranker._WARNED.clear()
    yield
    reranker._WARNED.clear()


class FakeResponse:
    def __init__(self, data=None, *, status_code: int = 200, json_error=None):
        self._data = data
        self.status_code = status_code
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://127.0.0.1:8081/v1/rerank")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._data


def test_fts_query_text_prefix_adds_only_alphabetic_prefixes() -> None:
    assert _fts_query_text_prefix("can i2c tegra234") == (
        "can | can:* | i2c | i2c:* | tegra234"
    )
    assert _fts_query_text_prefix("can2") == "can2"
    assert ":*" not in _fts_query_text_prefix("12")


def test_rerank_parses_sigmoid_sorts_and_truncates(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, RERANK_TOP_K=2)
    response = FakeResponse(
        {
            "results": [
                {"index": 0, "relevance_score": -2.359},
                {"index": 2, "relevance_score": 1.25},
                {"index": 1, "relevance_score": 0.0},
            ]
        }
    )
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(reranker.httpx, "post", fake_post)

    ranked = reranker.rerank("can", ["first", "second", "third"], 2, settings)

    assert [index for index, _ in ranked] == [2, 1]
    assert math.isclose(reranker._sigmoid(-2.359), 0.0863535, rel_tol=1e-5)
    assert calls == [
        (
            settings.reranker_url,
            {
                "json": {
                    "query": "can",
                    "documents": ["first", "second", "third"],
                },
                "headers": {"Content-Type": "application/json"},
                "timeout": settings.reranker_timeout_sec,
            },
        )
    ]


def test_rerank_truncates_oversized_documents(tmp_path: Path, monkeypatch) -> None:
    """Case candidates concatenate a whole git patch; untruncated they reached 85k
    tokens and llama-server rejected the batch with HTTP 500."""
    settings = make_settings(tmp_path, RERANK_TOP_K=1)
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs["json"])
        return FakeResponse({"results": [{"index": 0, "relevance_score": 1.0}]})

    monkeypatch.setattr(reranker.httpx, "post", fake_post)
    reranker.rerank("can", ["x" * 50_000], 1, settings)

    assert len(sent["documents"][0]) == reranker._MAX_DOC_CHARS


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        FakeResponse(status_code=500),
        FakeResponse(json_error=ValueError("invalid JSON")),
        FakeResponse({"results": [{"index": 0, "relevance_score": 1.0}]}),
    ],
    ids=["connection", "timeout", "http-500", "malformed-json", "count-mismatch"],
)
def test_rerank_failures_return_none_scores(
    tmp_path: Path,
    monkeypatch,
    failure,
) -> None:
    settings = make_settings(tmp_path, RERANK_TOP_K=2)

    def fake_post(*args, **kwargs):
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(reranker.httpx, "post", fake_post)

    assert reranker.rerank("can", ["first", "second", "third"], 2, settings) == [
        (0, None),
        (1, None),
    ]


def test_reranker_warning_is_emitted_once_per_endpoint(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    settings = make_settings(tmp_path)
    monkeypatch.setattr(
        reranker.httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )

    with caplog.at_level(logging.WARNING, logger="agent.tools.reranker"):
        reranker.rerank("can", ["first"], 1, settings)
        reranker.rerank("can", ["first"], 1, settings)

    messages = [record.message for record in caplog.records]
    assert len(messages) == 1
    assert "using ts_rank order" in messages[0]


def test_only_top_cases_carry_a_patch_excerpt(tmp_path: Path) -> None:
    """A 73k bundle once buried the answer; only the best matches keep a diff."""
    from agent.tools.doc_knowledge import _MAX_CASES_WITH_PATCH, _attach_patch_excerpts

    patch = (
        "diff --git a/p.dtsi b/p.dtsi\n--- a/p.dtsi\n+++ b/p.dtsi\n"
        "@@ -1 +1 @@\n-nvidia,function = \"rsvd1\";\n+nvidia,function = \"can2_dout\";\n"
    )
    ranked = [
        {"source_type": "MIC-741 case", "case_key": f"RE-{i}", "patch_content": patch}
        for i in range(5)
    ]
    _attach_patch_excerpts(ranked, "CAN pins reserved", [], make_settings(tmp_path))

    with_patch = [r for r in ranked if r.get("patch_excerpt")]
    assert len(with_patch) == _MAX_CASES_WITH_PATCH
    # The kept ones are the highest ranked, and patch_content never leaks through.
    assert [r["case_key"] for r in with_patch] == ["RE-0", "RE-1"]
    assert all("patch_content" not in r for r in ranked)


def test_rendered_bundle_is_bounded_and_keeps_the_top_match() -> None:
    from agent.tools.doc_knowledge import _MAX_BUNDLE_CHARS, _render_candidates

    rows = [
        {
            "source_type": "document",
            "doc_key": f"doc-{i}",
            "title": f"Doc {i}",
            "content": "x" * 6000,
            "rerank_score": 1.0 - i / 100,
        }
        for i in range(10)
    ]
    out = _render_candidates(rows)

    assert len(out) <= _MAX_BUNDLE_CHARS + 2000  # tail note plus the whole top entry
    assert "Doc 0" in out  # the best match is never dropped
    assert "omitted to bound context size" in out


def test_unavailable_reranker_is_visible_in_rendered_output() -> None:
    from agent.tools.doc_knowledge import _render_rank_line

    assert _render_rank_line({"rerank_score": 0.4321}) == "Cross-encoder score: 0.4321"
    # A genuine zero is still reported as a score, not as degradation.
    assert _render_rank_line({"rerank_score": 0.0}) == "Cross-encoder score: 0.0000"
    assert _render_rank_line({"rerank_score": None}) == (
        "Ranking: ts_rank order (cross-encoder unavailable)"
    )
    assert _render_rank_line({}) == "Ranking: ts_rank order (cross-encoder unavailable)"


def test_query_all_knowledge_merges_sources_in_cross_encoder_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = make_settings(tmp_path, RERANK_TOP_K=3)
    case = {
        "case_key": "RE-16",
        "title": "Restore pinmux",
        "subsystem": "pinmux",
        "commit_sha": "abc123",
        "issue_markdown": "CAN pins were reserved.",
        "solution_summary": "Restore CAN2 pinmux fields.",
        "repair_rule": "Match the board template.",
        "matches": ["CAN2_DOUT"],
        "patch_content": (
            "diff --git a/pinmux.dtsi b/pinmux.dtsi\n"
            "--- a/pinmux.dtsi\n"
            "+++ b/pinmux.dtsi\n"
            "@@ -1 +1 @@\n-old CAN2_DOUT\n+new CAN2_DOUT\n"
        ),
    }
    document = {
        "source_type": "document",
        "candidate_id": "doc-1",
        "doc_key": "thor-design-guide-v1.3",
        "title": "Thor Design Guide",
        "platform": "Thor",
        "doc_version": "1.3",
        "chunk_type": "table",
        "section_path": "Pinmux",
        "page": 42,
        "content": "CAN controller routing rules.",
        "ball": None,
        "signal_name": None,
        "rank": 0.3,
    }
    pin = {
        "source_type": "pinmux pin",
        "candidate_id": "pin-1",
        "doc_key": "thor-pinmux-v1.7",
        "title": "Thor Pinmux Template",
        "platform": "Thor",
        "doc_version": "1.7",
        "chunk_type": "pinmux_pin",
        "section_path": None,
        "page": None,
        "content": "Pin C17 CAN2_DOUT.",
        "ball": "C17",
        "signal_name": "CAN2_DOUT",
        "rank": 0.4,
    }
    monkeypatch.setattr("agent.tools.doc_knowledge._query_rows", lambda *args, **kwargs: [case])
    monkeypatch.setattr(
        "agent.tools.doc_knowledge._query_doc_candidates",
        lambda *args, **kwargs: [document, pin],
    )
    calls = []

    def fake_rerank(query, documents, top_k, passed_settings):
        calls.append((query, documents, top_k, passed_settings))
        return [(0, 0.95), (2, 0.8), (1, 0.7)]

    monkeypatch.setattr("agent.tools.doc_knowledge.rerank", fake_rerank)

    markdown = query_all_knowledge("restore CAN2 pins", [], settings)

    assert len(calls) == 1
    assert markdown.index("[pinmux pin]") < markdown.index("[MIC-741 case]")
    assert markdown.index("[MIC-741 case]") < markdown.index("[document]")
    assert "Ball: C17" in markdown
    assert "Signal: CAN2_DOUT" in markdown
    assert "Page: 42" in markdown
    assert "Chunk type: table" in markdown
    assert "@@ -1 +1 @@" in markdown


def test_query_doc_knowledge_renders_provenance(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, RERANK_TOP_K=1)
    row = {
        "source_type": "document",
        "candidate_id": "doc-1",
        "doc_key": "thor-datasheet-v1.4",
        "title": "Thor Datasheet",
        "platform": "Thor",
        "doc_version": "1.4",
        "chunk_type": "prose",
        "section_path": "Interfaces / CAN",
        "page": 18,
        "content": "The CAN interface uses these pins.",
        "ball": None,
        "signal_name": None,
        "rank": 0.5,
    }
    monkeypatch.setattr(
        "agent.tools.doc_knowledge._query_doc_candidates", lambda *args, **kwargs: [row]
    )
    monkeypatch.setattr(
        "agent.tools.doc_knowledge.rerank", lambda *args, **kwargs: [(0, 0.75)]
    )

    markdown = query_doc_knowledge("CAN interface", [], settings)

    assert markdown.startswith("## Reference Knowledge (docs / pinmux)")
    assert "Document: Thor Datasheet (`thor-datasheet-v1.4`)" in markdown
    assert "Page: 18" in markdown
    assert "Chunk type: prose" in markdown
