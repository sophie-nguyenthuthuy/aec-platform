"""LLM-driven and DB-driven node tests for `apps/ml/pipelines/winwork.py`.

The 3 pure helpers (`_construction_cost_per_sqm`, `_node_confidence`,
`_extract_json`) live in `test_winwork_pipeline_pure.py`. This file
covers the 4 nodes that touch the outside world:

  * `_node_benchmark_lookup`  — DB SELECT against `fee_benchmarks`
  * `_node_precedents`        — DB SELECT against `proposals` + JOIN `projects`
  * `_node_scope_expansion`   — Anthropic call returning a structured JSON
  * `_node_proposal_draft`    — Anthropic call returning title + notes

For each LLM node we assert (a) the right system-prompt language is
chosen by the `language` state, (b) the JSON output is parsed into the
state, and (c) the malformed-JSON fallback path produces a usable
state instead of crashing the pipeline.

Strategy
--------
DB nodes: build a minimal fake `AsyncSession` whose `execute()` returns
canned `mappings().all()` rows. Pattern matches the api-side router
tests (`apps/api/tests/test_costpulse_router.py::FakeAsyncSession`).

LLM nodes: monkeypatch `apps.ml.pipelines.winwork._llm` with a fake
that captures the messages and returns a preset `_StubLLMResponse`.
We don't go through the real `ChatAnthropic` constructor at all.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


# ---------- Fake session for DB nodes ----------


class _FakeSession:
    """Records executes; returns programmable `.mappings().all()` rows."""

    def __init__(self, rows_per_call: list[list[dict[str, Any]]]) -> None:
        self._rows = list(rows_per_call)
        self.executed_stmts: list[Any] = []
        self.executed_params: list[dict[str, Any]] = []

    async def execute(self, stmt, params=None):
        self.executed_stmts.append(stmt)
        self.executed_params.append(params or {})
        rows = self._rows.pop(0) if self._rows else []
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result


def _deps(session):
    """Build a `PipelineDeps` with the canned session.

    Imported lazily so any unrelated import error in the pipeline module
    fails the test rather than blocking collection.
    """
    from apps.ml.pipelines.winwork import PipelineDeps

    return PipelineDeps(session=session)


# ============================================================
# _node_benchmark_lookup
# ============================================================


async def test_benchmark_lookup_returns_first_band_when_rows_exist():
    """Multiple bands ordered by `area_sqm_min ASC` — the first row wins.

    The route SELECTs in that order intentionally: smaller-area bands
    are more conservative and we'd rather under-quote than over-quote a
    new client. Pin the ORDER BY behaviour via the canned row order.
    """
    from apps.ml.pipelines.winwork import _node_benchmark_lookup

    rows = [
        {
            "fee_percent_low": 6.0,
            "fee_percent_mid": 8.5,
            "fee_percent_high": 11.0,
            "source": "VARC 2024",
            "province": "HCMC",
        },
        {  # second band — must NOT be picked
            "fee_percent_low": 4.0,
            "fee_percent_mid": 5.0,
            "fee_percent_high": 7.0,
            "source": "VARC 2024",
            "province": "HCMC",
        },
    ]
    session = _FakeSession(rows_per_call=[rows])
    state = {"discipline": "architecture", "project_type": "residential_villa"}

    out = await _node_benchmark_lookup(state, _deps(session))

    assert out["benchmark"] == {
        "low": 6.0,
        "mid": 8.5,
        "high": 11.0,
        "source": "VARC 2024",
        "province": "HCMC",
    }
    # Bind params reach the SQL — discipline + project_type from state.
    assert session.executed_params[0] == {
        "d": "architecture",
        "pt": "residential_villa",
    }


async def test_benchmark_lookup_returns_none_when_no_rows():
    """Empty result must yield `benchmark: None` — not a partial dict
    with NaNs. Downstream `_node_fee_calculation` falls back to a
    {5/7.5/10} default when benchmark is None, so the absence-signal
    matters."""
    from apps.ml.pipelines.winwork import _node_benchmark_lookup

    session = _FakeSession(rows_per_call=[[]])
    state = {"discipline": "civil", "project_type": "obscure_type"}

    out = await _node_benchmark_lookup(state, _deps(session))

    assert out["benchmark"] is None


async def test_benchmark_lookup_coerces_null_columns_to_zero():
    """`fee_percent_low/mid/high` are nullable in the schema. The node
    must coerce NULL → 0.0 (via `or 0`) so the float() cast doesn't
    crash. A row with all-null percents is unusable but better to
    surface as `low=0.0` than to NoneType-error the whole pipeline."""
    from apps.ml.pipelines.winwork import _node_benchmark_lookup

    rows = [
        {
            "fee_percent_low": None,
            "fee_percent_mid": None,
            "fee_percent_high": None,
            "source": "Stub",
            "province": None,
        }
    ]
    session = _FakeSession(rows_per_call=[rows])
    out = await _node_benchmark_lookup(
        {"discipline": "mep", "project_type": "infrastructure"}, _deps(session)
    )

    assert out["benchmark"] == {
        "low": 0.0,
        "mid": 0.0,
        "high": 0.0,
        "source": "Stub",
        "province": None,
    }


async def test_benchmark_lookup_preserves_other_state_fields():
    from apps.ml.pipelines.winwork import _node_benchmark_lookup

    session = _FakeSession(rows_per_call=[[]])
    state = {
        "discipline": "architecture",
        "project_type": "residential_villa",
        "area_sqm": 500.0,
        "client_brief": "modern villa",
    }
    out = await _node_benchmark_lookup(state, _deps(session))
    assert out["area_sqm"] == 500.0
    assert out["client_brief"] == "modern villa"


# ============================================================
# _node_precedents
# ============================================================


async def test_precedents_returns_won_proposals_only():
    """The SQL filters `WHERE p.status = 'won'` — assert the bind
    params reflect that the org_id + project_type from state are
    passed through. We can't assert the WHERE clause directly here
    (the SQL is a literal text() block), but we can assert the bind
    map matches what the route builds."""
    from apps.ml.pipelines.winwork import _node_precedents

    rows = [
        {
            "id": "p1",
            "title": "Marina Bay Villa",
            "scope_of_work": {"items": []},
            "fee_breakdown": {"total_vnd": 800_000_000},
            "total_fee_vnd": 800_000_000,
        },
        {
            "id": "p2",
            "title": "Thao Dien Townhouse",
            "scope_of_work": None,
            "fee_breakdown": None,
            "total_fee_vnd": 500_000_000,
        },
    ]
    session = _FakeSession(rows_per_call=[rows])
    state = {"org_id": "org-1", "project_type": "residential_villa"}

    out = await _node_precedents(state, _deps(session))

    assert len(out["precedents"]) == 2
    assert out["precedents"][0]["id"] == "p1"
    assert out["precedents"][0]["title"] == "Marina Bay Villa"
    assert out["precedents"][1]["total_fee_vnd"] == 500_000_000
    # Bind params from state.
    assert session.executed_params[0] == {
        "org": "org-1",
        "pt": "residential_villa",
    }


async def test_precedents_empty_returns_empty_list_not_none():
    """No matches → empty list. Downstream nodes (scope_expansion,
    confidence) iterate `state["precedents"]` without a None guard."""
    from apps.ml.pipelines.winwork import _node_precedents

    session = _FakeSession(rows_per_call=[[]])
    out = await _node_precedents({"org_id": "org-1", "project_type": "x"}, _deps(session))
    assert out["precedents"] == []


# ============================================================
# _node_scope_expansion (LLM-driven)
# ============================================================


class _FakeLLMResp:
    def __init__(self, content) -> None:
        self.content = content


def _patch_llm(monkeypatch, fake_llm):
    """Replace `_llm()` factory with one that returns the fake. The node
    code calls `_llm().ainvoke(...)` so the factory must return an object
    with an async `ainvoke` method."""
    monkeypatch.setattr(
        "apps.ml.pipelines.winwork._llm",
        lambda: fake_llm,
    )


class _CapturingFakeLLM:
    """Captures messages + returns canned content."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.captured_messages: list[Any] = []

    async def ainvoke(self, messages):
        self.captured_messages = messages
        return _FakeLLMResp(self._content)


async def test_scope_expansion_parses_llm_json_into_scope_of_work(monkeypatch):
    from apps.ml.pipelines.winwork import _node_scope_expansion

    payload = {
        "items": [
            {
                "id": "s1",
                "phase": "Concept",
                "title": "Concept design",
                "description": "Initial sketches.",
                "deliverables": ["Moodboard", "Floor plan"],
                "hours_estimate": 40,
            },
            {
                "id": "s2",
                "phase": "Construction Documents",
                "title": "Final drawings",
                "deliverables": ["DWG set"],
                "hours_estimate": 120,
            },
        ]
    }
    fake = _CapturingFakeLLM(json.dumps(payload))
    _patch_llm(monkeypatch, fake)

    state = {
        "project_type": "residential_villa",
        "area_sqm": 500.0,
        "floors": 2,
        "location": "HCMC",
        "discipline": "architecture",
        "scope_items": ["concept", "construction documents"],
        "client_brief": "Modern villa with garden.",
        "language": "vi",
    }
    out = await _node_scope_expansion(state, _deps=None)

    assert out["scope_of_work"] == payload
    # Other state fields survive the spread.
    assert out["project_type"] == "residential_villa"


async def test_scope_expansion_picks_vietnamese_when_language_vi(monkeypatch):
    """Pin the language → system-prompt mapping. A regression that
    swapped the ternary direction would silently drop every Vietnamese
    proposal into English."""
    from apps.ml.pipelines.winwork import _node_scope_expansion

    fake = _CapturingFakeLLM(json.dumps({"items": []}))
    _patch_llm(monkeypatch, fake)

    await _node_scope_expansion(
        {
            "project_type": "x",
            "area_sqm": 1.0,
            "floors": 1,
            "location": "HCMC",
            "discipline": "architecture",
            "scope_items": [],
            "client_brief": "",
            "language": "vi",
        },
        _deps=None,
    )

    system_msg = fake.captured_messages[0]
    assert "Vietnamese" in system_msg.content
    assert "English" not in system_msg.content


async def test_scope_expansion_picks_english_when_language_en(monkeypatch):
    from apps.ml.pipelines.winwork import _node_scope_expansion

    fake = _CapturingFakeLLM(json.dumps({"items": []}))
    _patch_llm(monkeypatch, fake)

    await _node_scope_expansion(
        {
            "project_type": "x",
            "area_sqm": 1.0,
            "floors": 1,
            "location": "HCMC",
            "discipline": "architecture",
            "scope_items": [],
            "client_brief": "",
            "language": "en",
        },
        _deps=None,
    )

    system_msg = fake.captured_messages[0]
    assert "English" in system_msg.content


async def test_scope_expansion_falls_back_when_llm_returns_invalid_json(monkeypatch):
    """Critical robustness: a malformed LLM response must NOT crash the
    pipeline. The fallback wraps each scope_item the user originally
    typed into a `phase: "Concept"` placeholder so the proposal still
    has structure (even if it's not as detailed as Claude's output).

    Common breakage shape: model returns plain-text "I cannot..." which
    isn't JSON. Pin the fallback so a future refactor doesn't drop it."""
    from apps.ml.pipelines.winwork import _node_scope_expansion

    fake = _CapturingFakeLLM("not JSON, just prose")
    _patch_llm(monkeypatch, fake)

    state = {
        "project_type": "x",
        "area_sqm": 1.0,
        "floors": 1,
        "location": "HCMC",
        "discipline": "architecture",
        "scope_items": ["concept", "construction"],
        "client_brief": "",
        "language": "vi",
    }
    out = await _node_scope_expansion(state, _deps=None)

    assert out["scope_of_work"]["items"] == [
        {"id": "fallback", "phase": "Concept", "title": "concept", "deliverables": []},
        {
            "id": "fallback",
            "phase": "Concept",
            "title": "construction",
            "deliverables": [],
        },
    ]


async def test_scope_expansion_user_message_includes_precedent_titles(monkeypatch):
    """The user-message JSON includes `precedents: [titles]` so Claude
    can reference past proposals without the full payload (which would
    blow the context window). Pin that the projection happens client-
    side, not just "send everything." """
    from apps.ml.pipelines.winwork import _node_scope_expansion

    fake = _CapturingFakeLLM(json.dumps({"items": []}))
    _patch_llm(monkeypatch, fake)

    await _node_scope_expansion(
        {
            "project_type": "residential_villa",
            "area_sqm": 1.0,
            "floors": 1,
            "location": "HCMC",
            "discipline": "architecture",
            "scope_items": [],
            "client_brief": "",
            "language": "en",
            "precedents": [
                {"id": "p1", "title": "Marina Bay Villa", "scope_of_work": {}},
                {"id": "p2", "title": "Thao Dien Townhouse", "scope_of_work": {}},
            ],
        },
        _deps=None,
    )

    user_msg = fake.captured_messages[1]
    user_payload = json.loads(user_msg.content)
    # Just titles, not full scope_of_work.
    assert user_payload["precedents"] == ["Marina Bay Villa", "Thao Dien Townhouse"]


# ============================================================
# _node_proposal_draft (LLM-driven)
# ============================================================


async def test_proposal_draft_parses_title_and_notes(monkeypatch):
    from apps.ml.pipelines.winwork import _node_proposal_draft

    fake = _CapturingFakeLLM(json.dumps({"title": "Marina Bay Villa Proposal", "notes": "..."}))
    _patch_llm(monkeypatch, fake)

    state = {
        "project_type": "residential_villa",
        "area_sqm": 500.0,
        "floors": 2,
        "location": "HCMC",
        "client_brief": "Modern villa.",
        "scope_of_work": {"items": []},
        "fee_breakdown": {"total_vnd": 1_000_000_000},
        "language": "vi",
    }
    out = await _node_proposal_draft(state, _deps=None)

    assert out["title"] == "Marina Bay Villa Proposal"
    assert out["notes"] == "..."


async def test_proposal_draft_falls_back_with_synthetic_title_on_invalid_json(
    monkeypatch,
):
    """If the LLM returns garbage, the node fabricates a synthetic title
    (`Proposal — {project_type} — {location}`) and uses the client
    brief as the notes. Same robustness rationale as scope_expansion's
    fallback — the proposal table can't have NULL titles."""
    from apps.ml.pipelines.winwork import _node_proposal_draft

    fake = _CapturingFakeLLM("malformed: yes")
    _patch_llm(monkeypatch, fake)

    state = {
        "project_type": "residential_villa",
        "area_sqm": 500.0,
        "floors": 2,
        "location": "HCMC",
        "client_brief": "Modern villa.",
        "scope_of_work": {"items": []},
        "fee_breakdown": {"total_vnd": 1_000_000_000},
        "language": "en",
    }
    out = await _node_proposal_draft(state, _deps=None)

    assert out["title"] == "Proposal — residential_villa — HCMC"
    assert out["notes"] == "Modern villa."


async def test_proposal_draft_picks_vietnamese_executive_summary_when_lang_vi(
    monkeypatch,
):
    from apps.ml.pipelines.winwork import _node_proposal_draft

    fake = _CapturingFakeLLM(json.dumps({"title": "T", "notes": "N"}))
    _patch_llm(monkeypatch, fake)

    await _node_proposal_draft(
        {
            "project_type": "x",
            "area_sqm": 1.0,
            "floors": 1,
            "location": "HCMC",
            "client_brief": "",
            "scope_of_work": {},
            "fee_breakdown": {"total_vnd": 0},
            "language": "vi",
        },
        _deps=None,
    )

    system_msg = fake.captured_messages[0]
    assert "Vietnamese" in system_msg.content


async def test_proposal_draft_user_message_includes_fee_total(monkeypatch):
    """The cover-letter prompt includes `fee_total_vnd` so Claude can
    reference the bottom-line number ('Tổng phí thiết kế đề xuất là 1,2
    tỷ VND'). Without this, every generated cover letter would be
    fee-blind. Pin that the value is forwarded."""
    from apps.ml.pipelines.winwork import _node_proposal_draft

    fake = _CapturingFakeLLM(json.dumps({"title": "T", "notes": "N"}))
    _patch_llm(monkeypatch, fake)

    await _node_proposal_draft(
        {
            "project_type": "x",
            "area_sqm": 1.0,
            "floors": 1,
            "location": "HCMC",
            "client_brief": "",
            "scope_of_work": {"items": [{"phase": "Concept"}]},
            "fee_breakdown": {"total_vnd": 1_234_000_000},
            "language": "vi",
        },
        _deps=None,
    )

    user_msg = fake.captured_messages[1]
    user_payload = json.loads(user_msg.content)
    assert user_payload["fee_total_vnd"] == 1_234_000_000
    # And the scope_of_work survives the round-trip.
    assert user_payload["scope_of_work"] == {"items": [{"phase": "Concept"}]}
