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
