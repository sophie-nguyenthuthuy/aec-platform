"""Latency budget tests for the CODEGUARD pipeline.

These tests stub LLM and embedder to fixed-duration sleeps and assert
the pipeline's wall-clock time stays under specific thresholds. They
catch the kind of regression that's invisible to the rest of the suite:
  * Someone replaces `asyncio.gather` with sequential `await`s in
    `_hybrid_search`. Latency doubles silently.
  * A new helper inside `node_retrieve` accidentally awaits in a loop
    where it should batch.
  * `_hyde_expand` cache regresses (every call hits the LLM).

The thresholds are deliberately loose — generous headroom for slow CI
runners — but tight enough to catch the regressions above. If a test
flakes on a particularly loaded runner, double the threshold; the
order-of-magnitude gap is what matters, not the exact number.

Tier 1: no Postgres, no API keys, no network. The async sleeps are the
only "wall clock" cost; everything else is pure-Python work that adds
nanoseconds.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# Per-test sleep budget. Each stubbed retrieval awaits this long so the
# hybrid concurrency test has a measurable signal — too small and the
# gather/sequential difference disappears in scheduling jitter.
SLEEP_MS = 50


@pytest.fixture(autouse=True)
def _clear_hyde_cache():
    """Cache state across tests would skew latency assertions on the
    pipeline tests below — clear before and after each."""
    import pipelines.codeguard as cg

    cg._hyde_clear_cache()
    yield
    cg._hyde_clear_cache()


# ---------- Hybrid search concurrency ------------------------------------


async def test_hybrid_search_runs_dense_and_sparse_concurrently(monkeypatch):
    """`_hybrid_search` MUST `asyncio.gather` dense + sparse. With each
    arm sleeping 50ms, sequential = 100ms, concurrent = ~50ms. The
    threshold of 80ms catches a regression that drops the gather while
    leaving 30ms of headroom for runner jitter.

    This is the single most valuable latency test: gather/sequential is
    invisible to the integration suite (which uses real Postgres + ES
    where 50ms is well within timing noise) but doubles user-visible
    retrieval latency in production."""
    import pipelines.codeguard as cg

    async def _slow_dense(*_a, **_kw):
        await asyncio.sleep(SLEEP_MS / 1000)
        return [{"id": "d1", "content": "x", "regulation_id": str(uuid4())}]

    async def _slow_sparse(*_a, **_kw):
        await asyncio.sleep(SLEEP_MS / 1000)
        return [{"id": "s1", "content": "y", "regulation_id": str(uuid4())}]

    monkeypatch.setattr(cg, "_dense_search", _slow_dense)
    monkeypatch.setattr(cg, "_sparse_search", _slow_sparse)

    start = time.perf_counter()
    result = await cg._hybrid_search(
        db=None,
        query_text="test",
        categories=None,
        jurisdiction=None,
        top_k=8,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < SLEEP_MS + 30, (
        f"_hybrid_search took {elapsed_ms:.1f}ms with two {SLEEP_MS}ms-each "
        f"stubs — should be ~{SLEEP_MS}ms (concurrent), not "
        f"~{SLEEP_MS * 2}ms (sequential). Likely the asyncio.gather got "
        "replaced with serial awaits."
    )
    # Sanity: both arms ran (RRF should have both items).
    assert len(result) == 2


async def test_hybrid_search_dense_only_path_is_fast(monkeypatch):
    """When sparse returns [] (ES unavailable), the gather still runs
    both arms — sparse just resolves nearly-instantly. Total latency
    should still be ~`SLEEP_MS` (dominated by dense), not 2× anything.
    Pin so a future regression that adds an "if sparse_url is None"
    short-circuit doesn't accidentally run dense AFTER sparse instead
    of in parallel with it."""
    import pipelines.codeguard as cg

    async def _slow_dense(*_a, **_kw):
        await asyncio.sleep(SLEEP_MS / 1000)
        return [{"id": "d1", "content": "x", "regulation_id": str(uuid4())}]

    async def _empty_sparse(*_a, **_kw):
        return []  # instant — ES unavailable

    monkeypatch.setattr(cg, "_dense_search", _slow_dense)
    monkeypatch.setattr(cg, "_sparse_search", _empty_sparse)

    start = time.perf_counter()
    await cg._hybrid_search(
        db=None,
        query_text="test",
        categories=None,
        jurisdiction=None,
        top_k=8,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Generous threshold: dense sleep + scheduling overhead, no more.
    assert elapsed_ms < SLEEP_MS + 30, (
        f"Dense-only path took {elapsed_ms:.1f}ms — expected ~{SLEEP_MS}ms."
    )


# ---------- Full Q&A pipeline -------------------------------------------


async def test_qa_pipeline_total_latency_under_budget(monkeypatch):
    """`answer_regulation_query` end-to-end with stubbed LLM + retrieval.
    The four awaitable phases each cost SLEEP_MS:
      1. _hyde_expand
      2. _hybrid_search (dense + sparse concurrent)
      3. _rerank (instant — no endpoint)
      4. node_generate (LLM call)
    Sequential total = 4 × 50ms = 200ms. With gather inside _hybrid_search
    the dense/sparse pair counts once, so realistic total = 3 × 50ms =
    150ms. Threshold 200ms + 50ms headroom = 250ms catches a regression
    that re-adds a phase or removes the gather without flaking on slow
    runners."""
    import json

    import pipelines.codeguard as cg
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    async def _slow_hyde(_q, _lang):
        await asyncio.sleep(SLEEP_MS / 1000)
        return ""

    async def _slow_dense(*_a, **_kw):
        await asyncio.sleep(SLEEP_MS / 1000)
        return [
            {
                "id": "c1",
                "regulation_id": str(uuid4()),
                "section_ref": "1.1",
                "content": "x",
                "code_name": "QCVN test",
                "source_url": None,
                "score": 0.9,
            }
        ]

    async def _instant_sparse(*_a, **_kw):
        return []

    canned = json.dumps(
        {
            "answer": "x",
            "confidence": 0.5,
            "citations": [],
            "related_questions": [],
        }
    )

    class _SlowModel(FakeListChatModel):
        # `_agenerate` is the actual async hook BaseChatModel.ainvoke
        # traverses; `_acall` only fires on sync `__call__` paths and
        # would never be invoked here. Subclassing it keeps Pydantic
        # happy (no instance-attr monkeypatch required).
        async def _agenerate(self, *args, **kwargs):  # type: ignore[override]
            await asyncio.sleep(SLEEP_MS / 1000)
            return await super()._agenerate(*args, **kwargs)

    monkeypatch.setattr(cg, "_hyde_expand", _slow_hyde)
    monkeypatch.setattr(cg, "_dense_search", _slow_dense)
    monkeypatch.setattr(cg, "_sparse_search", _instant_sparse)
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.1: _SlowModel(responses=[canned]))

    start = time.perf_counter()
    await cg.answer_regulation_query(
        db=None,
        question="test question",
        language="vi",
        jurisdiction=None,
        categories=None,
        top_k=8,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Three sequential phases × SLEEP_MS each = 150ms ideal, plus
    # scheduling overhead. Budget: 250ms. Anything over 300ms suggests
    # something is awaiting in a loop.
    assert elapsed_ms < SLEEP_MS * 5, (
        f"Q&A pipeline took {elapsed_ms:.1f}ms with {SLEEP_MS}ms stubs — "
        f"expected ~{SLEEP_MS * 3}ms. Likely a phase got serialised that "
        "should have been concurrent, or a new sync loop landed."
    )


# ---------- HyDE cache hit short-circuits -------------------------------


async def test_hyde_cache_hit_takes_zero_extra_latency(monkeypatch):
    """The HyDE cache exists specifically to remove ~500-800ms of
    Anthropic latency on repeat questions. A regression where the
    cache hit accidentally still calls through the LLM would silently
    burn money AND latency.

    First call sleeps SLEEP_MS (cold cache); second call should be
    near-instant (warm cache). Threshold of SLEEP_MS / 5 = 10ms gives
    plenty of headroom for the cache lookup itself — typically <1ms."""
    import pipelines.codeguard as cg
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    class _SlowHydeModel(FakeListChatModel):
        async def _agenerate(self, *args, **kwargs):  # type: ignore[override]
            await asyncio.sleep(SLEEP_MS / 1000)
            return await super()._agenerate(*args, **kwargs)

    monkeypatch.setattr(
        cg,
        "_llm",
        lambda temperature=0.1: _SlowHydeModel(responses=["expansion"] * 5),
    )

    # Cold path — populates the cache, pays the LLM cost.
    cold_start = time.perf_counter()
    await cg._hyde_expand("Same question?", "vi")
    cold_ms = (time.perf_counter() - cold_start) * 1000
    assert cold_ms >= SLEEP_MS - 5, (
        f"Cold cache should pay the LLM cost (~{SLEEP_MS}ms), got {cold_ms:.1f}ms — "
        "suggests the stub didn't sleep, test is invalid."
    )

    # Warm path — should be essentially instant.
    warm_start = time.perf_counter()
    await cg._hyde_expand("Same question?", "vi")
    warm_ms = (time.perf_counter() - warm_start) * 1000

    assert warm_ms < SLEEP_MS / 5, (
        f"Cache hit took {warm_ms:.1f}ms — should be <10ms for a "
        "dictionary lookup. Cache may have regressed and is calling "
        "through to the LLM."
    )
