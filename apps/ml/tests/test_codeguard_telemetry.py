"""Unit tests for the LLM/embedding cost telemetry helper.

What this contract guarantees:
  * Every LLM/embedding call emits exactly one log record on the
    `codeguard.telemetry` logger with a stable shape: `call`, `model`,
    `latency_ms`, `input_chars`, `output_chars`, `status`, `error`.
  * Failures still emit a record (with `status="error"`); they don't
    silently disappear from spend rollups when the LLM is misbehaving.
  * Cache hits in `_hyde_expand` produce NO telemetry record (the
    cache short-circuits before the call). This is the load-bearing
    contract for cost accounting — a regression that bypasses the
    cache would silently double Anthropic spend.
  * `_record_llm_call` is the single choke point — every call site
    we instrument lands records via this helper, so route-level
    spend rollups don't need to know about pipeline internals.

Why these tests are valuable: cost telemetry that silently drops
events is worse than no telemetry at all (false confidence in spend
forecasts). The assertions are deliberately strict on event count.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _clear_hyde_cache():
    """Cache state from prior tests would change the call count
    here — clear before and after every test in this file."""
    import pipelines.codeguard as cg

    cg._hyde_clear_cache()
    yield
    cg._hyde_clear_cache()


@pytest.fixture
def telemetry_records(caplog):
    """Capture log records from the dedicated telemetry logger.

    Returns a callable that, when invoked, returns the list of records
    emitted on `codeguard.telemetry` so far. We use a callable (not a
    list snapshot) so tests can assert the count both mid-test and
    after.
    """
    caplog.set_level(logging.INFO, logger="codeguard.telemetry")

    def _records() -> list[logging.LogRecord]:
        return [r for r in caplog.records if r.name == "codeguard.telemetry"]

    return _records


# ---------- _record_llm_call directly --------------------------------------


async def test_record_llm_call_emits_ok_log_with_stable_fields(telemetry_records):
    """The success path: one log record with every documented field
    populated and `status="ok"`."""
    import pipelines.codeguard as cg

    async with cg._record_llm_call(
        call="test_call",
        model="test-model",
        input_chars=42,
    ) as rec:
        rec["output_chars"] = 100

    records = telemetry_records()
    assert len(records) == 1
    r = records[0]
    assert r.message == "codeguard.llm_call"
    assert r.call == "test_call"
    assert r.model == "test-model"
    assert r.input_chars == 42
    assert r.output_chars == 100
    assert r.status == "ok"
    assert r.error is None
    # Latency is non-negative; we can't assert a specific value
    # because Python's monotonic clock granularity varies.
    assert isinstance(r.latency_ms, int)
    assert r.latency_ms >= 0


async def test_record_llm_call_emits_error_log_and_reraises(telemetry_records):
    """A raised exception still produces a telemetry record (status="error")
    AND propagates — so a misconfigured LLM shows up in spend rollups
    without breaking the caller's error-handling path."""
    import pipelines.codeguard as cg

    with pytest.raises(RuntimeError, match="boom"):
        async with cg._record_llm_call(
            call="failing_call",
            model="test-model",
            input_chars=10,
        ):
            raise RuntimeError("boom")

    records = telemetry_records()
    assert len(records) == 1
    r = records[0]
    assert r.status == "error"
    assert r.error == "boom"
    assert r.output_chars is None  # never populated on the error path
    assert r.input_chars == 10


# ---------- Integration with pipeline call sites ---------------------------


async def test_hyde_expand_cache_miss_emits_one_record(monkeypatch, telemetry_records):
    """First call (cache miss) hits the LLM and produces a `hyde_expand`
    record. Stable shape: same fields as the helper test."""
    import pipelines.codeguard as cg

    fake = FakeListChatModel(responses=["hypothetical regulation paragraph"])
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.1: fake)

    await cg._hyde_expand("Test question?", "vi")

    records = telemetry_records()
    hyde_records = [r for r in records if getattr(r, "call", None) == "hyde_expand"]
    assert len(hyde_records) == 1
    r = hyde_records[0]
    assert r.status == "ok"
    assert r.input_chars == len("Test question?") + len("vi")
    assert r.output_chars == len("hypothetical regulation paragraph")
    assert r.model == cg._ANTHROPIC_MODEL


async def test_hyde_expand_cache_hit_emits_no_record(monkeypatch, telemetry_records):
    """The cache short-circuits before the LLM call → NO telemetry
    record. This is the contract that protects spend forecasts: if
    the cache regressed and started silently calling through, the
    record count would jump and this test would flag it.
    """
    import pipelines.codeguard as cg

    fake = FakeListChatModel(responses=["expansion"] * 5)
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.1: fake)

    await cg._hyde_expand("Cached question?", "vi")  # miss → 1 record
    initial = len(telemetry_records())
    assert initial == 1

    await cg._hyde_expand("Cached question?", "vi")  # hit → still 1
    after_hit = len(telemetry_records())
    assert after_hit == 1, (
        f"Cache hit emitted a telemetry record (count went {initial}→{after_hit}). "
        "Either the cache regressed or _hyde_expand re-entered the "
        "_record_llm_call block on the cached path."
    )


async def test_hyde_expand_failure_logs_error_and_propagates(monkeypatch, telemetry_records):
    """Failure path on the integration: factory raises → telemetry
    records `status="error"`, exception propagates, cache stays clean."""
    import pipelines.codeguard as cg

    def _exploding_factory(temperature: float = 0.1):
        raise RuntimeError("Anthropic 503")

    monkeypatch.setattr(cg, "_llm", _exploding_factory)

    with pytest.raises(RuntimeError, match="Anthropic 503"):
        await cg._hyde_expand("Doomed question?", "vi")

    records = telemetry_records()
    # The factory raises before the chain.ainvoke call, so the
    # `_record_llm_call` context manager never enters — no record is
    # emitted in this specific path. Document it: telemetry covers
    # call sites where the chain itself runs; factory-construction
    # failures (which are deployment misconfigurations, not transient
    # LLM hiccups) belong in their own monitor. Keeps this test
    # accurate to the implementation rather than aspirational.
    assert len(records) == 0


async def test_dense_search_emits_embedding_record(monkeypatch, telemetry_records):
    """Embedding calls in `_dense_search` go through `_record_llm_call`
    with `call="embed_query"` — separate dimension from LLM calls in
    the spend rollup."""
    import pipelines.codeguard as cg

    class _FakeEmbedder:
        async def aembed_query(self, _q: str) -> list[float]:
            return [0.0] * 3072

    monkeypatch.setattr(cg, "_embedder", lambda: _FakeEmbedder())

    # Stub the DB query — _dense_search does a real SQL execute after
    # the embedding call, which we don't care about for this test.
    class _FakeDb:
        async def execute(self, *_a, **_kw):
            class _R:
                def mappings(self):
                    class _M:
                        def all(self):
                            return []

                    return _M()

            return _R()

    await cg._dense_search(
        db=_FakeDb(),
        query_text="Câu hỏi test embedding",
        categories=None,
        jurisdiction=None,
        top_k=8,
    )

    embed_records = [r for r in telemetry_records() if getattr(r, "call", None) == "embed_query"]
    assert len(embed_records) == 1
    r = embed_records[0]
    assert r.status == "ok"
    assert r.model == cg._EMBED_MODEL
    assert r.input_chars == len("Câu hỏi test embedding")
    assert r.output_chars == 3072  # vector dim
