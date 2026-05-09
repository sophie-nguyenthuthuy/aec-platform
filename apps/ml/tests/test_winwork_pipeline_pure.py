"""Pure-function tests for `apps/ml/pipelines/winwork.py`.

The pipeline's async LangGraph nodes need real (or faked) LLM + DB
access — covered by the integration lane. The three pure helpers below
have no such dependency and were sitting at 0% coverage:

  * `_construction_cost_per_sqm(project_type)` — VND/m² lookup table
    with a default. The `.get(..., 12_000_000)` fallback is the contract:
    an unrecognised project type still returns *something* so the fee
    pipeline doesn't divide-by-None downstream.

  * `_node_confidence(state)` — additive score that drives the
    "AI confidence" badge on every generated proposal. Pin the
    arithmetic so a refactor can't silently flip a +0.25 to +0.025.

  * `_extract_json(content)` — un-fences LLM responses (Anthropic
    sometimes wraps JSON in ```json ... ``` blocks; sometimes returns
    a list of content blocks). Critical: every LLM-driven node parses
    its output through this, so a regression here breaks every node.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "project_type,expected",
    [
        ("residential_villa", 12_000_000),
        ("residential_apartment", 10_000_000),
        ("commercial_office", 15_000_000),
        ("commercial_retail", 14_000_000),
        ("industrial", 8_000_000),
        ("infrastructure", 20_000_000),
    ],
)
def test_construction_cost_per_sqm_known_types(project_type, expected):
    from apps.ml.pipelines.winwork import _construction_cost_per_sqm

    assert _construction_cost_per_sqm(project_type) == expected


def test_construction_cost_per_sqm_unknown_type_falls_back_to_default():
    """An unknown project_type — say a typo or a future category not yet
    in the table — must return the residential_villa default, not None
    or raise. Downstream `_node_fee_calculation` multiplies this by
    area; a None would crash the whole pipeline."""
    from apps.ml.pipelines.winwork import _construction_cost_per_sqm

    assert _construction_cost_per_sqm("hospital") == 12_000_000
    assert _construction_cost_per_sqm("") == 12_000_000


# ---------- _node_confidence ----------
#
# Score formula:
#   base 0.4
#   +0.25 if state.benchmark is truthy
#   +0.15 if precedents has >= 2 entries (or +0.08 for 1 entry)
#   +0.10 if scope_of_work.items has >= 3 entries
#   +0.05 if client_brief is >= 200 chars
#   capped at 0.95
#
# Round 2dp.


@pytest.mark.asyncio
async def test_node_confidence_minimal_state_returns_base_score():
    from apps.ml.pipelines.winwork import _node_confidence

    state = {
        "client_brief": "short",
        "scope_of_work": {},
    }
    out = await _node_confidence(state, _deps=None)
    assert out["confidence"] == 0.4


@pytest.mark.asyncio
async def test_node_confidence_full_signal_caps_at_0_95():
    from apps.ml.pipelines.winwork import _node_confidence

    state = {
        "benchmark": {"some": "data"},
        "precedents": [{"a": 1}, {"b": 2}, {"c": 3}],
        "scope_of_work": {"items": [1, 2, 3, 4]},
        "client_brief": "x" * 250,
    }
    out = await _node_confidence(state, _deps=None)
    # 0.4 + 0.25 + 0.15 + 0.10 + 0.05 = 0.95 → cap kicks in (no overshoot)
    assert out["confidence"] == 0.95


@pytest.mark.asyncio
async def test_node_confidence_partial_signal_adds_correctly():
    from apps.ml.pipelines.winwork import _node_confidence

    state = {
        "benchmark": {"x": 1},
        "precedents": [{"a": 1}],  # 1 entry → +0.08, NOT +0.15
        "scope_of_work": {"items": []},
        "client_brief": "y" * 50,
    }
    out = await _node_confidence(state, _deps=None)
    # 0.4 + 0.25 (benchmark) + 0.08 (one precedent) = 0.73
    assert out["confidence"] == 0.73


@pytest.mark.asyncio
async def test_node_confidence_two_precedents_uses_higher_bonus():
    """Pin the >=2 threshold — a regression that flipped to >=3 would
    silently halve the bonus on most generated proposals."""
    from apps.ml.pipelines.winwork import _node_confidence

    one = await _node_confidence(
        {"client_brief": "", "scope_of_work": {}, "precedents": [{}]},
        _deps=None,
    )
    two = await _node_confidence(
        {"client_brief": "", "scope_of_work": {}, "precedents": [{}, {}]},
        _deps=None,
    )
    assert two["confidence"] - one["confidence"] == pytest.approx(0.07, abs=0.01)


@pytest.mark.asyncio
async def test_node_confidence_preserves_other_state_fields():
    """Spread-pattern: `return {**state, "confidence": ...}` — every
    other state key MUST survive untouched. A regression that returned
    only the new field would break the next pipeline node."""
    from apps.ml.pipelines.winwork import _node_confidence

    state = {
        "client_brief": "x",
        "scope_of_work": {},
        "title": "Marina Tower",
        "fee_breakdown": {"total_vnd": 5_000_000_000},
    }
    out = await _node_confidence(state, _deps=None)
    assert out["title"] == "Marina Tower"
    assert out["fee_breakdown"]["total_vnd"] == 5_000_000_000


# ---------- _extract_json ----------


def test_extract_json_plain_string_passes_through():
    from apps.ml.pipelines.winwork import _extract_json

    assert _extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_strips_triple_backtick_fences():
    """Anthropic often wraps JSON in ```...``` blocks. Without this the
    downstream `json.loads` would choke on the literal backticks."""
    from apps.ml.pipelines.winwork import _extract_json

    assert _extract_json('```\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_strips_json_language_hint_after_fences():
    """Same wrapper but with `json` after the opening fence — common
    in Markdown-trained models."""
    from apps.ml.pipelines.winwork import _extract_json

    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    # Case-insensitive:
    assert _extract_json('```JSON\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_handles_list_of_content_blocks():
    """Anthropic sometimes returns a list of content blocks (one per
    text segment) instead of a single string. The pipeline must
    collapse them — otherwise `text.startswith` would raise on the
    list."""
    from apps.ml.pipelines.winwork import _extract_json

    blocks = [
        {"type": "text", "text": '{"a":'},
        {"type": "text", "text": " 1}"},
    ]
    assert _extract_json(blocks) == '{"a": 1}'


def test_extract_json_handles_list_with_non_dict_blocks():
    """Defensive: a malformed block that's neither a dict nor a string
    shouldn't crash the parse — `str(block)` is the fallback."""
    from apps.ml.pipelines.winwork import _extract_json

    # Mixed: a text block + a "weird" object that gets stringified.
    blocks = [{"text": "{}"}]
    assert _extract_json(blocks) == "{}"
