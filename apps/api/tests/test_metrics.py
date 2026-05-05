"""Tests for the stdlib Prometheus metrics module + `/metrics` endpoint.

Two layers:
  1. Pure unit tests on `Counter` / `Histogram` / `Gauge` semantics + the
     text-exposition renderer.
  2. End-to-end: hit the FastAPI app, walk through `/health` to populate
     counters, then `/metrics` and assert the output parses and contains
     the expected series.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------- Primitives ----------


def test_counter_increments_per_label_set():
    from core.metrics import Counter

    c = Counter("foo", ["route"])
    c.inc({"route": "/a"})
    c.inc({"route": "/a"})
    c.inc({"route": "/b"})

    # Read internal state — fine for a unit test.
    assert c._values[("/a",)] == 2.0
    assert c._values[("/b",)] == 1.0


def test_histogram_bucketing_is_cumulative():
    """`observe(0.05)` must tick every bucket whose `le` >= 0.05.
    Renderer reads buckets directly so they need to be cumulative
    at observation time."""
    from core.metrics import Histogram

    h = Histogram(
        "lat_seconds",
        ["route"],
        buckets=(0.01, 0.1, 1.0, 10.0),
    )
    h.observe(0.05, {"route": "/a"})
    row = h._observations[("/a",)]
    # row layout: [sum, count, b0, b1, b2, b3]
    assert row[0] == 0.05
    assert row[1] == 1.0
    assert row[2] == 0.0  # le=0.01 — does NOT include 0.05
    assert row[3] == 1.0  # le=0.1  — INCLUDES
    assert row[4] == 1.0  # le=1.0  — INCLUDES
    assert row[5] == 1.0  # le=10   — INCLUDES


def test_gauge_overwrites_value():
    from core.metrics import Gauge

    g = Gauge("queue_depth", [])
    g.set(5.0)
    g.set(3.0)  # gauges replace, not add
    assert g._values[()] == 3.0


# ---------- Renderer ----------


def test_render_emits_help_and_type_lines():
    from core.metrics import _REGISTRY, Counter, render

    # Snapshot the registry, replace with a deterministic singleton, restore.
    saved = list(_REGISTRY)
    try:
        _REGISTRY.clear()
        c = Counter("test_total", ["status"], help_text="for tests")
        _REGISTRY.append(c)
        c.inc({"status": "200"}, value=3)

        text = render()
        assert "# HELP test_total for tests" in text
        assert "# TYPE test_total counter" in text
        assert 'test_total{status="200"} 3.0' in text
    finally:
        _REGISTRY.clear()
        _REGISTRY.extend(saved)


def test_render_handles_empty_metric_with_zero_row():
    """A metric with no observations should still appear, so dashboards
    don't break the first time a process boots before any traffic."""
    from core.metrics import _REGISTRY, Counter, render

    saved = list(_REGISTRY)
    try:
        _REGISTRY.clear()
        _REGISTRY.append(Counter("never_inc", []))
        text = render()
        assert "never_inc 0" in text
    finally:
        _REGISTRY.clear()
        _REGISTRY.extend(saved)


def test_render_escapes_label_values():
    """Quotes and backslashes inside label values must be escaped per
    the Prometheus exposition spec — otherwise a parser sees a syntax
    error at scrape time."""
    from core.metrics import _REGISTRY, Counter, render

    saved = list(_REGISTRY)
    try:
        _REGISTRY.clear()
        c = Counter("evil", ["k"])
        _REGISTRY.append(c)
        c.inc({"k": 'has"quote and\\slash'})

        text = render()
        # Must contain escaped form, NOT raw.
        assert r"has\"quote and\\slash" in text
        assert 'k="has"' not in text
    finally:
        _REGISTRY.clear()
        _REGISTRY.extend(saved)


def test_render_histogram_emits_bucket_sum_count_lines():
    from core.metrics import _REGISTRY, Histogram, render

    saved = list(_REGISTRY)
    try:
        _REGISTRY.clear()
        h = Histogram("lat", ["route"], buckets=(0.1, 1.0))
        _REGISTRY.append(h)
        h.observe(0.5, {"route": "/x"})

        text = render()
        # Bucket lines.
        assert 'lat_bucket{route="/x",le="0.1"} 0' in text
        assert 'lat_bucket{route="/x",le="1.0"} 1' in text
        assert 'lat_bucket{route="/x",le="+Inf"} 1' in text
        assert 'lat_sum{route="/x"} 0.5' in text
        assert 'lat_count{route="/x"} 1' in text
    finally:
        _REGISTRY.clear()
        _REGISTRY.extend(saved)


# ---------- End-to-end ----------


async def test_metrics_endpoint_returns_prometheus_text(monkeypatch):
    """Hit /health, then /metrics. The middleware should have ticked
    the http_requests_total counter for /health."""

    # Stub the queue-depth probe — we don't want it touching Redis.
    async def _fake_sample():
        from core.metrics import arq_queue_depth

        arq_queue_depth.set(0.0)

    monkeypatch.setattr("core.metrics._sample_queue_depth", _fake_sample)

    # Patch sample point in main.py too — it imports lazily inside the
    # endpoint so monkeypatching the module-level attr in core.metrics
    # is the one that matters.

    import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First request populates the counter.
        await ac.get("/health")
        # Second request: scrape.
        res = await ac.get("/metrics")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    body = res.text
    # The /health request should have ticked the counter.
    assert "http_requests_total" in body
    assert 'route="/health"' in body
    # The histogram families show up too.
    assert "http_request_duration_seconds_bucket" in body
    assert "http_request_duration_seconds_sum" in body
    # Gauge present even after the test stub.
    assert "arq_queue_depth" in body


# ---------- Codeguard cap-check metrics --------------------------------
#
# The cap-check counter + histogram are registered at module import,
# so they're always advertised in /metrics output (HELP/TYPE lines).
# What's NOT pinned by the unit-level metric tests:
#
#   * The metric NAMES match what dashboards scrape — a typo at the
#     `_register(Counter("..."))` site only surfaces when the dashboard
#     query returns nothing, which is exactly the regression an end-
#     to-end scrape test catches at PR time.
#   * The HELP / TYPE lines actually render (the renderer treats
#     histograms differently from counters; both must work).
#   * After a cap-check fires, the counter's `{limit_kind="..."}` line
#     and the histogram's `_bucket` / `_sum` / `_count` lines all
#     appear in the scrape output. Pinned via direct calls into the
#     helper rather than a /query round-trip — avoids dragging in the
#     LLM mock fixture for what's a metrics-renderer pin.


async def test_metrics_endpoint_advertises_codeguard_quota_metrics():
    """Both cap-check metrics announce themselves via HELP/TYPE lines
    even before any cap-check has fired — `_register` makes them visible
    at module import. Pin the names + types so a regression that renames
    them silently breaks every dashboard that scrapes by name."""
    import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    assert res.status_code == 200
    body = res.text

    # Counter: announced as a counter, even with no observations yet.
    assert "# TYPE codeguard_quota_429_total counter" in body, (
        "Counter `codeguard_quota_429_total` missing from /metrics output. "
        "Either it didn't get registered, or the renderer dropped its "
        "TYPE line."
    )
    # Histogram: announced as a histogram (the renderer's histogram
    # branch is distinct from the counter branch — pin both code paths).
    assert "# TYPE codeguard_quota_check_duration_seconds histogram" in body, (
        "Histogram `codeguard_quota_check_duration_seconds` missing TYPE "
        "line. Did `_register(Histogram(...))` regress to plain Counter, "
        "or did the renderer's histogram branch break?"
    )


async def test_metrics_endpoint_renders_429_counter_after_cap_check_fires():
    """After firing the cap-check helper directly with an over-limit
    stub, /metrics shows the labelled `{limit_kind="input"}` series and
    the histogram emits bucket/sum/count lines. End-to-end pin: the
    instrumentation in `_check_quota_or_raise` actually flows through
    the renderer all the way to the scrape body."""
    from uuid import uuid4

    import main

    # Stub the quota check at the service-module level so the cap-check
    # path takes the over-limit branch without touching a DB.
    import services.codeguard_quotas as _q_module
    from routers.codeguard import _check_quota_or_raise
    from services.codeguard_quotas import QuotaCheckResult

    saved = _q_module.check_org_quota

    async def _over_quota(_db, _org_id):
        return QuotaCheckResult(over_limit=True, limit_kind="input", used=1_500_000, limit=1_000_000)

    _q_module.check_org_quota = _over_quota
    try:
        # Fire the helper. It raises 429 — suppress and ignore; we
        # only care about the metric side-effect.
        import contextlib as _ctx

        from fastapi import HTTPException

        with _ctx.suppress(HTTPException):
            await _check_quota_or_raise(None, uuid4())  # type: ignore[arg-type]
    finally:
        _q_module.check_org_quota = saved

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    body = res.text

    # Counter has at least one observation under the labelled series.
    # Match `codeguard_quota_429_total{limit_kind="input"} <number>` —
    # don't pin the exact count because other tests in this run may
    # have ticked the same series.
    assert 'codeguard_quota_429_total{limit_kind="input"}' in body, (
        'Expected a labelled `{limit_kind="input"}` series in the scrape '
        "output after firing the cap-check. Either the counter's `.inc()` "
        "stopped binding the label or the renderer skipped the row."
    )

    # Histogram has bucket + sum + count lines.
    assert "codeguard_quota_check_duration_seconds_bucket" in body, (
        "Histogram bucket lines missing — observe() didn't fire, or the "
        "renderer's histogram branch isn't producing bucket rows."
    )
    assert "codeguard_quota_check_duration_seconds_sum" in body
    assert "codeguard_quota_check_duration_seconds_count" in body
    # The `+Inf` bucket terminates the histogram series — without it
    # Prometheus parsers refuse the family.
    assert 'codeguard_quota_check_duration_seconds_bucket{le="+Inf"}' in body
