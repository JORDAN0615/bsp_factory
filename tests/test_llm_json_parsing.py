"""A reply that is not pure JSON must still yield parseable JSON.

Models rarely answer with JSON alone: reasoning models prefix a `<think>…</think>`
block, others add a line of preamble. The original stripper only handled a fence
at position 0, so every `json.loads` call site failed at "line 1 column 1" — in
practice the Code Review Agent degraded to `needs_human` on every single run
without anyone noticing. These cases must keep working across model swaps.
"""
import json

from agent.tools.llm_tools import strip_json_fence


def test_think_block_before_fenced_json() -> None:
    raw = (
        "<think>Let me analyze this patch.\n"
        "It modifies the pinmux file.</think>\n\n"
        '```json\n{"decision": "pass", "confidence": 0.85}\n```'
    )
    assert json.loads(strip_json_fence(raw)) == {"decision": "pass", "confidence": 0.85}


def test_think_block_before_bare_json() -> None:
    raw = '<think>reasoning here</think>\n{"decision": "reject"}'
    assert json.loads(strip_json_fence(raw)) == {"decision": "reject"}


def test_unterminated_think_block_still_recovers() -> None:
    """A truncated reply can leave `<think>` unclosed; the JSON must survive."""
    raw = '<think>reasoning that never closes\n```json\n{"decision": "pass"}\n```'
    assert json.loads(strip_json_fence(raw)) == {"decision": "pass"}


def test_prose_around_bare_json() -> None:
    raw = 'Here is my review:\n{"decision": "pass"}\nHope that helps.'
    assert json.loads(strip_json_fence(raw)) == {"decision": "pass"}


def test_json_array_payload() -> None:
    raw = "<think>ranking</think>\n```json\n[{\"case\": \"RE-16\"}]\n```"
    assert json.loads(strip_json_fence(raw)) == [{"case": "RE-16"}]


def test_plain_fenced_json_still_works() -> None:
    assert json.loads(strip_json_fence('```json\n{"a": 1}\n```')) == {"a": 1}


def test_plain_json_unchanged() -> None:
    assert json.loads(strip_json_fence('{"a": 1}')) == {"a": 1}
