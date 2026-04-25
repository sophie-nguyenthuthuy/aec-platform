"""Unit tests for hybrid retrieval: `_reciprocal_rank_fusion` + `_hybrid_search`.

These are pure-logic tests — dense and sparse retrieval are stubbed so we
don't need Postgres or Elasticsearch. The properties we care about:

  * RRF math is correct (score formula, rank ordering, overlap handling).
  * `_hybrid_search` runs dense + sparse concurrently via `asyncio.gather`.
  * Graceful dense-only fallback when sparse returns [] (covers the common
    prod case: ES transient outage / ES package not installed in a given
    deployment). The result shape must be identical to dense-only output
    — no missing keys, no score renormalisation surprises.
  * `sparse_query` override flows through to `_sparse_search` (HyDE-dilute
    protection for Q&A) while dense gets the full `query_text`.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------- _reciprocal_rank_fusion --------------------------------------


def _doc(doc_id: str, score: float = 0.0) -> dict:
    return {"id": doc_id, "content": f"content-{doc_id}", "score": score}


def test_rrf_preserves_dense_only_order_when_sparse_empty():
    """Graceful-degradation contract: sparse outage must not change dense ranking."""
    from pipelines.codeguard import _reciprocal_rank_fusion

    dense = [_doc("a"), _doc("b"), _doc("c")]
    fused = _reciprocal_rank_fusion(dense, [])
    assert [d["id"] for d in fused] == ["a", "b", "c"]


def test_rrf_preserves_sparse_only_order_when_dense_empty():
    """Symmetric: dense failure (shouldn't happen for us, but defensive)."""
    from pipelines.codeguard import _reciprocal_rank_fusion

    sparse = [_doc("x"), _doc("y")]
    fused = _reciprocal_rank_fusion([], sparse)
    assert [d["id"] for d in fused] == ["x", "y"]


def test_rrf_overlap_boosts_docs_seen_in_both_lists():
    """A doc ranked #2 in both lists outranks a doc ranked #1 in one only,
    once the second-list contribution lifts its RRF score high enough.

    With k=60 (module default):
      - doc "shared" at rank 1 in dense + rank 1 in sparse:
          score = 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.0328
      - doc "dense-only" at rank 0 in dense only:
          score = 1/(60+0+1) = 1/61 ≈ 0.0164

    wait — rank 0 is better than rank 1. Let me redo this more carefully:
      - "dense-only" at dense rank 0: 1/(60+0+1) = 1/61
      - "shared" at dense rank 1 + sparse rank 0: 1/62 + 1/61 ≈ 0.0326
    So "shared" (≈0.0326) beats "dense-only" (≈0.0164). Good — the fusion
    rewards cross-list agreement, which is the whole point of hybrid.
    """
    from pipelines.codeguard import _reciprocal_rank_fusion

    dense = [_doc("dense-only"), _doc("shared")]
    sparse = [_doc("shared"), _doc("sparse-only")]
    fused = _reciprocal_rank_fusion(dense, sparse)
    order = [d["id"] for d in fused]
    assert order[0] == "shared", f"cross-list agreement should win, got {order}"
    # The other two appear after; exact order depends on k but "shared" is top.


def test_rrf_returns_union_of_both_lists():
    """No doc dropped; deduplication is by `id`."""
    from pipelines.codeguard import _reciprocal_rank_fusion

    dense = [_doc("a"), _doc("b")]
    sparse = [_doc("b"), _doc("c")]
    fused = _reciprocal_rank_fusion(dense, sparse)
    ids = sorted(d["id"] for d in fused)
    assert ids == ["a", "b", "c"]


def test_rrf_uses_dense_payload_for_duplicates():
    """When the same `id` appears in both lists, the dense payload wins.
    Matters because dense has authoritative DB fields (regulation_id uuid,
    code_name from the JOIN); sparse has whatever ES happens to store.
    Not load-bearing today but codifies the contract."""
    from pipelines.codeguard import _reciprocal_rank_fusion

    dense_payload = {"id": "x", "content": "from-pg", "regulation_id": "uuid-1"}
    sparse_payload = {"id": "x", "content": "from-es", "regulation_id": "different"}
    fused = _reciprocal_rank_fusion([dense_payload], [sparse_payload])
    assert fused[0]["content"] == "from-pg"
    assert fused[0]["regulation_id"] == "uuid-1"


def test_rrf_empty_inputs_returns_empty():
    from pipelines.codeguard import _reciprocal_rank_fusion

    assert _reciprocal_rank_fusion([], []) == []


# ---------- _hybrid_search -----------------------------------------------


async def test_hybrid_search_runs_dense_and_sparse_concurrently(monkeypatch):
    """Both retrievals should await concurrently — wall-clock for two 100ms
    stubs should be ~100ms total, not ~200ms. This is the latency win the
    facade exists to deliver."""
    import pipelines.codeguard as cg

    async def _slow_dense(*_args, **_kwargs):
        await asyncio.sleep(0.1)
        return [_doc("d")]

    async def _slow_sparse(*_args, **_kwargs):
        await asyncio.sleep(0.1)
        return [_doc("s")]

    monkeypatch.setattr(cg, "_dense_search", _slow_dense)
    monkeypatch.setattr(cg, "_sparse_search", _slow_sparse)

    start = time.perf_counter()
    fused = await cg._hybrid_search(
        db=None,
        query_text="q",
        categories=None,
        jurisdiction=None,
        top_k=5,
    )
    elapsed = time.perf_counter() - start

    # Serial would be ≥0.19s; concurrent should come in well under 0.15s.
    # Generous upper bound so the test isn't flaky on loaded CI runners.
    assert elapsed < 0.15, f"dense+sparse ran serially? elapsed={elapsed:.3f}s"
    assert {d["id"] for d in fused} == {"d", "s"}


async def test_hybrid_search_falls_back_to_dense_when_sparse_empty(monkeypatch):
    """ES outage contract: dense-only output must be a proper ranked list."""
    import pipelines.codeguard as cg

    dense_results = [_doc("a"), _doc("b"), _doc("c")]

    async def _dense(*_args, **_kwargs):
        return dense_results

    async def _sparse_empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(cg, "_dense_search", _dense)
    monkeypatch.setattr(cg, "_sparse_search", _sparse_empty)

    fused = await cg._hybrid_search(
        db=None,
        query_text="q",
        categories=None,
        jurisdiction=None,
        top_k=5,
    )
    assert [d["id"] for d in fused] == ["a", "b", "c"]


async def test_hybrid_search_passes_sparse_query_override(monkeypatch):
    """Q&A pipeline feeds HyDE-expanded text to dense but raw question to
    sparse — `sparse_query` override must reach `_sparse_search` unchanged."""
    import pipelines.codeguard as cg

    captured: dict = {}

    async def _dense(db, query_text, *_a, **_kw):
        captured["dense_q"] = query_text
        return []

    async def _sparse(query_text, *_a, **_kw):
        captured["sparse_q"] = query_text
        return []

    monkeypatch.setattr(cg, "_dense_search", _dense)
    monkeypatch.setattr(cg, "_sparse_search", _sparse)

    await cg._hybrid_search(
        db=None,
        query_text="question + hyde prose",
        categories=None,
        jurisdiction=None,
        top_k=5,
        sparse_query="question only",
    )
    assert captured["dense_q"] == "question + hyde prose"
    assert captured["sparse_q"] == "question only"


async def test_hybrid_search_defaults_sparse_query_to_query_text(monkeypatch):
    """Auto-scan has no HyDE — omitting `sparse_query` should send the same
    query to both retrievers."""
    import pipelines.codeguard as cg

    captured: dict = {}

    async def _dense(db, query_text, *_a, **_kw):
        captured["dense_q"] = query_text
        return []

    async def _sparse(query_text, *_a, **_kw):
        captured["sparse_q"] = query_text
        return []

    monkeypatch.setattr(cg, "_dense_search", _dense)
    monkeypatch.setattr(cg, "_sparse_search", _sparse)

    await cg._hybrid_search(
        db=None,
        query_text="same query",
        categories=None,
        jurisdiction=None,
        top_k=5,
    )
    assert captured["dense_q"] == captured["sparse_q"] == "same query"


async def test_sparse_search_logs_warning_on_es_failure(monkeypatch, caplog):
    """The silent `except Exception: return []` was masking ES outages in
    prod. Confirm the WARNING log is emitted so operators see the
    degradation in alerts."""
    import logging as _logging

    import pipelines.codeguard as cg

    # Stub `AsyncElasticsearch` to raise on .search() — simulates connection
    # refused / timeout. The module imports lazily inside _sparse_search so
    # we can't monkeypatch the class itself easily; patch the module's
    # elasticsearch reference via sys.modules shim.
    class _BoomES:
        def __init__(self, *_a, **_kw):
            pass

        async def search(self, *_a, **_kw):
            raise ConnectionError("ES down")

        async def close(self):
            pass

    fake_module = type(sys)("elasticsearch")
    fake_module.AsyncElasticsearch = _BoomES
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_module)

    with caplog.at_level(_logging.WARNING, logger="pipelines.codeguard"):
        out = await cg._sparse_search("q", None, None, 5)

    assert out == []
    assert any("BM25" in r.message or "Elasticsearch" in r.message for r in caplog.records), (
        f"expected ES-failure WARNING; got {[r.message for r in caplog.records]}"
    )
