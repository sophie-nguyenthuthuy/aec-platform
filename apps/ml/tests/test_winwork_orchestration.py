"""End-to-end orchestration tests for `apps/ml/pipelines/winwork.py`.

The 4 outside-world nodes are covered in `test_winwork_pipeline_nodes.py`.
The 3 pure helpers in `test_winwork_pipeline_pure.py`. This file pins the
**glue** between them — the LangGraph wiring + the `run_proposal_pipeline`
entry point that the WinWork router calls.

What we lock in
---------------
  1. **Node sequence**: the graph runs benchmark → precedents → scope →
     fee → draft → confidence in that order. Each downstream node sees
     the upstream node's state mutations. A regression that swapped
     edges (e.g. fee before scope, which would mean the fee calculator
     never sees the LLM-generated phase weights) would fire here.

  2. **Output projection**: the entry point returns
     `{title, notes, scope_of_work, fee_breakdown, confidence, ai_job_id}` —
     a strict subset of the final state. A new state field that
     accidentally leaked into the response would surface here.

  3. **Job-recording side effects**: `run_proposal_pipeline` writes
     three SQL rows over its lifetime — INSERT (running) → UPDATE
     (done) on success, or INSERT (running) → UPDATE (failed) on
     pipeline error. The audit-trail / retry-detection logic in the
     activity feed depends on this exact sequence.

Strategy
--------
We monkeypatch each `_node_*` function to a canned async returning the
target state mutation. This isolates orchestration from the node logic
that's already covered by `test_winwork_pipeline_nodes.py`. The fake
session captures every `execute()` call so we can assert the SQL flow.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


class _RecordingSession:
    """Minimal async session that records every `execute()` call."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        self.executes.append((str(stmt), params or {}))
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        return result


class _FakeRequest:
    """Minimal stand-in for `schemas.winwork.ProposalGenerateRequest`.

    The pipeline only reads attributes (`project_type`, `area_sqm`, ...)
    and calls `.model_dump(mode="json")`. We don't need a real Pydantic
    model — a SimpleNamespace-like object is enough.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def model_dump(self, mode: str = "json") -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _make_request(**overrides: Any) -> _FakeRequest:
    base: dict[str, Any] = dict(
        project_type="residential_villa",
        area_sqm=500.0,
        floors=2,
        location="HCMC",
        scope_items=["concept", "construction"],
        client_brief="Modern villa with garden in District 2.",
        discipline="architecture",
        language="vi",
    )
    base.update(overrides)
    return _FakeRequest(**base)


def _patch_nodes(monkeypatch, *, sequence: list[str]):
    """Replace every `_node_*` with a recorder + state-mutator. The
    `sequence` list captures call order so tests can assert it.

    Each node returns a state with one new key set so we can verify
    downstream nodes saw the upstream mutation."""

    async def benchmark(state, _deps):
        sequence.append("benchmark")
        return {**state, "benchmark": {"low": 5.0, "mid": 7.5, "high": 10.0}}

    async def precedents(state, _deps):
        sequence.append("precedents")
        return {**state, "precedents": [{"id": "p1", "title": "Marina Bay"}]}

    async def scope(state, _deps):
        sequence.append("scope")
        # Scope assertion below depends on this content.
        return {
            **state,
            "scope_of_work": {
                "items": [
                    {"phase": "Concept"},
                    {"phase": "Schematic"},
                    {"phase": "Construction Documents"},
                ]
            },
        }

    async def fee(state, _deps):
        sequence.append("fee")
        # Fee node sees `state["benchmark"]` set by the upstream node —
        # if the graph wiring re-ordered them, fee would receive a state
        # without `benchmark` and the test below catches it.
        assert state.get("benchmark") is not None, (
            "fee node ran before benchmark — graph wiring regression"
        )
        assert state.get("scope_of_work") is not None, (
            "fee node ran before scope — graph wiring regression"
        )
        return {
            **state,
            "fee_breakdown": {
                "lines": [],
                "subtotal_vnd": 1_000_000_000,
                "vat_vnd": 80_000_000,
                "total_vnd": 1_080_000_000,
            },
        }

    async def draft(state, _deps):
        sequence.append("draft")
        assert state.get("fee_breakdown") is not None
        return {**state, "title": "Marina Bay Villa Proposal", "notes": "Body."}

    async def confidence(state, _deps):
        sequence.append("confidence")
        return {**state, "confidence": 0.85}

    monkeypatch.setattr("apps.ml.pipelines.winwork._node_benchmark_lookup", benchmark)
    monkeypatch.setattr("apps.ml.pipelines.winwork._node_precedents", precedents)
    monkeypatch.setattr("apps.ml.pipelines.winwork._node_scope_expansion", scope)
    monkeypatch.setattr("apps.ml.pipelines.winwork._node_fee_calculation", fee)
    monkeypatch.setattr("apps.ml.pipelines.winwork._node_proposal_draft", draft)
    monkeypatch.setattr("apps.ml.pipelines.winwork._node_confidence", confidence)


# ============================================================
# _build_graph
# ============================================================


async def test_build_graph_runs_nodes_in_documented_order(monkeypatch):
    """The graph's edges enforce
    benchmark → precedents → scope → fee → draft → confidence.
    Pin the order — a regression that swaps edges would break the
    state-dependency invariants (fee needs benchmark + scope already
    set; draft needs fee already set)."""
    from apps.ml.pipelines.winwork import PipelineDeps, _build_graph

    sequence: list[str] = []
    _patch_nodes(monkeypatch, sequence=sequence)

    deps = PipelineDeps(session=_RecordingSession())
    graph = _build_graph(deps)

    final = await graph.ainvoke(
        {
            "org_id": "org-1",
            "project_type": "residential_villa",
            "area_sqm": 500.0,
            "floors": 2,
            "location": "HCMC",
            "scope_items": [],
            "client_brief": "",
            "discipline": "architecture",
            "language": "vi",
            "precedents": [],
        }
    )

    assert sequence == [
        "benchmark",
        "precedents",
        "scope",
        "fee",
        "draft",
        "confidence",
    ]
    # Final state has all node-produced fields.
    assert final["benchmark"] == {"low": 5.0, "mid": 7.5, "high": 10.0}
    assert final["precedents"][0]["title"] == "Marina Bay"
    assert final["scope_of_work"]["items"][0]["phase"] == "Concept"
    assert final["fee_breakdown"]["total_vnd"] == 1_080_000_000
    assert final["title"] == "Marina Bay Villa Proposal"
    assert final["confidence"] == 0.85


# ============================================================
# run_proposal_pipeline — happy path
# ============================================================


async def test_run_proposal_pipeline_returns_projected_output(monkeypatch):
    """The entry point returns a strict subset of the final state.
    Lock the projection: any new state field that leaks into the
    response would surface here."""
    from apps.ml.pipelines import winwork

    _patch_nodes(monkeypatch, sequence=[])
    session = _RecordingSession()
    org_id = uuid4()
    request = _make_request()

    output = await winwork.run_proposal_pipeline(session=session, org_id=org_id, request=request)

    # Exactly these keys, no more no less.
    assert set(output.keys()) == {
        "title",
        "notes",
        "scope_of_work",
        "fee_breakdown",
        "confidence",
        "ai_job_id",
    }
    assert output["title"] == "Marina Bay Villa Proposal"
    assert output["confidence"] == 0.85
    assert isinstance(output["ai_job_id"], UUID)


async def test_run_proposal_pipeline_writes_running_then_done(monkeypatch):
    """Successful pipeline writes 3 rows total:
       1. INSERT ai_jobs (status=running)
       3. UPDATE ai_jobs SET status=done, output=... (after the graph
          completes)
    (The 6 nodes in between are all monkeypatched so they don't write
    to the session.)

    Any regression that skipped the success-record would silently
    leak `running` rows in the ai_jobs table forever — that's the
    audit trail's "happy/sad" signal."""
    from apps.ml.pipelines import winwork

    _patch_nodes(monkeypatch, sequence=[])
    session = _RecordingSession()
    request = _make_request()

    await winwork.run_proposal_pipeline(session=session, org_id=uuid4(), request=request)

    # The session received exactly 2 SQL writes — the start INSERT
    # and the success UPDATE. Nodes are mocked so no other executes.
    sql_writes = [sql for sql, _ in session.executes]
    assert len(sql_writes) == 2
    assert "INSERT INTO ai_jobs" in sql_writes[0]
    assert "running" in sql_writes[0]
    # Success UPDATE.
    assert "UPDATE ai_jobs" in sql_writes[1]
    assert "done" in sql_writes[1]


async def test_run_proposal_pipeline_threads_org_id_into_running_row(monkeypatch):
    """The job-record bind params carry the right org_id — without
    this, every ai_job would land in the wrong tenant. RLS on the
    ai_jobs table would catch it but only if the connection is
    aec_app — better to assert the binding directly."""
    from apps.ml.pipelines import winwork

    _patch_nodes(monkeypatch, sequence=[])
    session = _RecordingSession()
    org_id = UUID("12345678-1234-5678-1234-567812345678")

    await winwork.run_proposal_pipeline(session=session, org_id=org_id, request=_make_request())

    # First execute — the INSERT — has the org_id bind.
    _sql, params = session.executes[0]
    assert params["org"] == str(org_id)
    # And the input column carries the JSON-serialized request.
    assert "residential_villa" in params["input"]


# ============================================================
# run_proposal_pipeline — error path
# ============================================================


async def test_run_proposal_pipeline_records_failure_when_node_raises(monkeypatch):
    """If any node raises mid-graph, the pipeline records the failure
    in `ai_jobs` and re-raises. Without the failure record the audit
    feed would silently drop the job — the user sees the 502 from the
    router, but operators never learn there was a downstream
    pipeline crash."""
    from apps.ml.pipelines import winwork

    sequence: list[str] = []
    _patch_nodes(monkeypatch, sequence=sequence)

    # Override scope to raise mid-graph.
    async def _scope_boom(_state, _deps):
        sequence.append("scope")
        raise RuntimeError("Anthropic 503")

    monkeypatch.setattr("apps.ml.pipelines.winwork._node_scope_expansion", _scope_boom)

    session = _RecordingSession()

    with pytest.raises(RuntimeError, match="Anthropic 503"):
        await winwork.run_proposal_pipeline(
            session=session, org_id=uuid4(), request=_make_request()
        )

    # Got far enough to record start + failure (no success).
    sql_writes = [sql for sql, _ in session.executes]
    assert "INSERT INTO ai_jobs" in sql_writes[0]
    assert any("status = 'failed'" in s for s in sql_writes), (
        "expected a failure UPDATE, got: " + repr(sql_writes)
    )
    # The failure UPDATE carries the exception message in its bind params.
    fail_call = next(
        (sql, params) for sql, params in session.executes if "status = 'failed'" in sql
    )
    assert fail_call[1]["err"] == "Anthropic 503"


async def test_run_proposal_pipeline_failure_carries_consistent_job_id(monkeypatch):
    """The INSERT (start) and the UPDATE (failure) target the same
    `ai_jobs.id`. A regression that allocated a new uuid for the
    failure write would leave the start row stuck in `running`
    forever."""
    from apps.ml.pipelines import winwork

    _patch_nodes(monkeypatch, sequence=[])

    async def _draft_boom(_state, _deps):
        raise RuntimeError("model timeout")

    monkeypatch.setattr("apps.ml.pipelines.winwork._node_proposal_draft", _draft_boom)

    session = _RecordingSession()

    with pytest.raises(RuntimeError):
        await winwork.run_proposal_pipeline(
            session=session, org_id=uuid4(), request=_make_request()
        )

    insert_id = session.executes[0][1]["id"]
    fail_id = next(params["id"] for sql, params in session.executes if "status = 'failed'" in sql)
    assert insert_id == fail_id
