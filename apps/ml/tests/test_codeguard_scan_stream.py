"""Unit tests for `pipelines.codeguard.auto_scan_project_stream`.

The streaming variant has its own contract distinct from the non-streaming
path: it yields one `category_start` + one `category_done` per category,
and per-category LLM exceptions are swallowed (the category yields zero
findings rather than killing the whole scan).

What this contract guarantees:
  * Categories yield in input order.
  * Each category emits exactly one `category_start` and one
    `category_done` regardless of retrieval/LLM outcomes.
  * Empty retrieval skips the LLM call (asserted by counting `_llm`
    factory calls) but still emits `category_done` with empty
    findings — so the UI has a signal to render the empty advisory.
  * A per-category LLM failure does NOT terminate the stream; the
    failing category emits `category_done` with empty findings, and
    subsequent categories still run.
  * Citation grounding still applies — same DB-row provenance as
    `auto_scan_project`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _candidates_for(category_name: str) -> list[dict]:
    """A retrieved chunk shaped like a `_dense_search` row, keyed
    enough to be distinguishable per-category in tests."""
    return [
        {
            "id": str(uuid4()),
            "regulation_id": str(uuid4()),
            "section_ref": f"§{category_name}-1",
            "content": f"chunk content for {category_name}",
            "code_name": f"QCVN-{category_name}",
            "source_url": None,
            "score": 0.9,
        },
    ]


@pytest.fixture(autouse=True)
def _clear_hyde_cache():
    """Streaming path doesn't use HyDE, but several tests in the dir do
    — keep cache state from leaking across files."""
    import pipelines.codeguard as cg

    cg._hyde_clear_cache()
    yield
    cg._hyde_clear_cache()


async def test_each_category_emits_one_start_and_one_done(monkeypatch):
    """Two categories scanned -> exactly four events: start/done x 2,
    in category-then-event order. No phantom or missing events.
    """
    import pipelines.codeguard as cg
    from schemas.codeguard import ProjectParameters, RegulationCategory

    # Hybrid search returns one chunk per category-specific query.
    candidates = _candidates_for("any")

    async def _hybrid(*_a, **_kw):
        return candidates

    async def _passthrough_rerank(_q, items, *_a, **_kw):
        return items

    monkeypatch.setattr(cg, "_hybrid_search", _hybrid)
    monkeypatch.setattr(cg, "_rerank", _passthrough_rerank)

    canned = json.dumps(
        {
            "findings": [
                {
                    "status": "PASS",
                    "severity": "minor",
                    "title": "OK",
                    "description": "All good.",
                    "resolution": None,
                    "citation_chunk_index": 0,
                }
            ]
        }
    )
    # Two LLM calls → cycle the same response.
    monkeypatch.setattr(
        cg, "_llm", lambda temperature=0.0: FakeListChatModel(responses=[canned, canned])
    )

    events: list[tuple[str, object]] = []
    async for ev in cg.auto_scan_project_stream(
        db=None,
        parameters=ProjectParameters(project_type="residential"),
        categories=[RegulationCategory.fire_safety, RegulationCategory.accessibility],
    ):
        events.append(ev)

    # Expected: start(fire) → done(fire) → start(access) → done(access).
    names = [e[0] for e in events]
    assert names == [
        "category_start",
        "category_done",
        "category_start",
        "category_done",
    ], names

    # Categories arrived in input order.
    assert events[0][1] == RegulationCategory.fire_safety
    assert events[2][1] == RegulationCategory.accessibility
    assert events[1][1]["category"] == RegulationCategory.fire_safety
    assert events[3][1]["category"] == RegulationCategory.accessibility


async def test_empty_retrieval_skips_llm_but_still_emits_done(monkeypatch):
    """No retrieval for a category → category_done with empty findings,
    no LLM call. Frontend can render "no issues found for X" advisory."""
    import pipelines.codeguard as cg
    from schemas.codeguard import ProjectParameters, RegulationCategory

    async def _empty_hybrid(*_a, **_kw):
        return []

    async def _passthrough_rerank(_q, items, *_a, **_kw):
        return items

    monkeypatch.setattr(cg, "_hybrid_search", _empty_hybrid)
    monkeypatch.setattr(cg, "_rerank", _passthrough_rerank)

    llm_calls: list[int] = []

    def _llm_factory(temperature: float = 0.0):
        llm_calls.append(1)
        return FakeListChatModel(responses=["unused"])

    monkeypatch.setattr(cg, "_llm", _llm_factory)

    events = [
        ev
        async for ev in cg.auto_scan_project_stream(
            db=None,
            parameters=ProjectParameters(project_type="residential"),
            categories=[RegulationCategory.fire_safety],
        )
    ]

    assert len(llm_calls) == 0, "LLM was called despite empty retrieval"
    assert [e[0] for e in events] == ["category_start", "category_done"]
    done_payload = events[1][1]
    assert done_payload["category"] == RegulationCategory.fire_safety
    assert done_payload["findings"] == []
    assert done_payload["reg_ids"] == []


async def test_per_category_llm_failure_does_not_kill_the_stream(monkeypatch):
    """One category's LLM raises → that category yields empty findings,
    next category still runs. The error event is reserved for hard
    pipeline failures, not per-category hiccups."""
    import pipelines.codeguard as cg
    from schemas.codeguard import ProjectParameters, RegulationCategory

    candidates = _candidates_for("any")

    async def _hybrid(*_a, **_kw):
        return candidates

    async def _passthrough_rerank(_q, items, *_a, **_kw):
        return items

    monkeypatch.setattr(cg, "_hybrid_search", _hybrid)
    monkeypatch.setattr(cg, "_rerank", _passthrough_rerank)

    # First call raises, second call returns one finding.
    second_canned = json.dumps(
        {
            "findings": [
                {
                    "status": "WARN",
                    "severity": "minor",
                    "title": "X",
                    "description": "Y",
                    "resolution": None,
                    "citation_chunk_index": 0,
                }
            ]
        }
    )

    invocation = {"n": 0}

    class _FlakyChain:
        def __init__(self, model):
            self.model = model

        def __or__(self, other):
            from langchain_core.runnables import RunnableSequence

            return RunnableSequence(self, other)

    # Simpler approach: provide a model whose .ainvoke fails on first
    # call only. Use a counter inside a small wrapper around
    # FakeListChatModel — but Pydantic blocks instance attrs, so we
    # patch _llm to return different models per call instead.
    def _llm_factory(temperature: float = 0.0):
        invocation["n"] += 1
        if invocation["n"] == 1:
            return _RaisingFakeModel(responses=["unused"])
        return FakeListChatModel(responses=[second_canned])

    monkeypatch.setattr(cg, "_llm", _llm_factory)

    events = [
        ev
        async for ev in cg.auto_scan_project_stream(
            db=None,
            parameters=ProjectParameters(project_type="residential"),
            categories=[RegulationCategory.fire_safety, RegulationCategory.accessibility],
        )
    ]

    # No `error` event — per-category failures are swallowed.
    assert all(e[0] != "error" for e in events), (
        f"Per-category failure leaked an error event: {events}"
    )

    # Both categories produced a `category_done`.
    done_events = [e for e in events if e[0] == "category_done"]
    assert len(done_events) == 2

    # First category: no findings (LLM failed). reg_ids still populated
    # because retrieval worked.
    fire = done_events[0][1]
    assert fire["category"] == RegulationCategory.fire_safety
    assert fire["findings"] == []
    assert len(fire["reg_ids"]) == 1

    # Second category: one finding from the canned response.
    access = done_events[1][1]
    assert access["category"] == RegulationCategory.accessibility
    assert len(access["findings"]) == 1
    assert access["findings"][0].title == "X"


async def test_findings_include_grounded_citations(monkeypatch):
    """Same Citation grounding contract as the non-streaming path:
    regulation_id + code_name + section come from the DB row, excerpt
    is the chunk content prefix (auto_scan never trusts the LLM's
    excerpt)."""
    import pipelines.codeguard as cg
    from schemas.codeguard import ProjectParameters, RegulationCategory

    candidates = _candidates_for("any")
    expected_reg_id = candidates[0]["regulation_id"]

    async def _hybrid(*_a, **_kw):
        return candidates

    async def _passthrough_rerank(_q, items, *_a, **_kw):
        return items

    monkeypatch.setattr(cg, "_hybrid_search", _hybrid)
    monkeypatch.setattr(cg, "_rerank", _passthrough_rerank)

    canned = json.dumps(
        {
            "findings": [
                {
                    "status": "FAIL",
                    "severity": "critical",
                    "title": "Issue",
                    "description": "details",
                    "resolution": "fix it",
                    "citation_chunk_index": 0,
                }
            ]
        }
    )
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.0: FakeListChatModel(responses=[canned]))

    events = [
        ev
        async for ev in cg.auto_scan_project_stream(
            db=None,
            parameters=ProjectParameters(project_type="residential"),
            categories=[RegulationCategory.fire_safety],
        )
    ]
    done = next(e for e in events if e[0] == "category_done")[1]
    finding = done["findings"][0]
    assert str(finding.citation.regulation_id) == expected_reg_id
    # Excerpt is taken from the chunk content (auto_scan doesn't
    # accept LLM-supplied excerpts).
    assert finding.citation.excerpt.startswith("chunk content for")


# ---------- Helpers -------------------------------------------------------


class _RaisingFakeModel(FakeListChatModel):
    """Fake chat model whose `ainvoke` raises. Used to simulate a
    per-category LLM hiccup without monkeypatching Pydantic-managed
    attributes on a normal FakeListChatModel instance."""

    async def _acall(self, *_a, **_kw):  # type: ignore[override]
        raise RuntimeError("Anthropic 503 simulated")
