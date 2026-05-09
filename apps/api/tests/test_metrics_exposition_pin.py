"""Pin `core.metrics` — Prometheus exposition format.

This module is the single source of truth for what Prometheus
scrapes from the `/metrics` endpoint. Two distinct surfaces in
one module, both with high cost-of-regression:

  * **Metric registry.** Series names + label sets that the
    platform's Grafana dashboards + alert rules `expr` against.
    A rename here = every dashboard panel that references the
    old name silently goes blank; every alert rule with the old
    name silently stops firing.

  * **Exposition format.** Prometheus's text format is
    deceptively strict — bucket boundaries MUST be deterministic
    strings (no `5e-3` vs `0.005` drift), labels MUST be
    double-quoted, special chars MUST be escaped. A regression
    in the renderer would break the scrape itself.

Specific failure modes a regression here can produce:

  * **`http_requests_total` label drift.** If `route` becomes the
    literal URL (e.g. `/api/v1/projects/abc-123-uuid`) instead of
    the route template (`/api/v1/projects/{project_id}`),
    cardinality explodes one-series-per-UUID and Prometheus
    storage detonates.

  * **`codeguard_quota_429_total` label cardinality.** Pinned to
    `["limit_kind"]` (2 distinct values: input|output). If a
    well-meaning dev adds an `org_id` label, cardinality goes
    from 2 to 2×N where N is the customer count — alerts time
    out, dashboards stutter.

  * **`EXTERNAL_METRIC_NAMES` drift.** This frozenset documents
    metric names produced OUTSIDE this module (by
    `routers/ops.py::_build_metrics_text`). The
    `scripts/validate_prometheus_rules.py` reads it to resolve
    alert-rule expressions. A drift = alert-rules that
    reference the missing names silently fail validation.

  * **Histogram bucket drift.** `DEFAULT_BUCKETS_SECONDS` is the
    set of latency boundaries every histogram emits a count for.
    Tightening or loosening shifts every Grafana percentile
    panel's interpretation.

  * **`-1` sentinel for unreachable Redis.** Grafana panels read
    `arq_queue_depth` and `-1` is the documented "Redis
    unreachable" sentinel — distinct from `0` (legit empty
    queue). A regression that emitted `0` on Redis failure
    would let "queue is broken" masquerade as "queue is empty."

This file is read-only. Survives reverts.
"""

from __future__ import annotations

import inspect

# ---------- Module presence ----------


def test_metrics_module_imports():
    """All public surfaces importable. Hard ImportError on revert =
    the desired loud signal vs silently broken metrics."""
    from core.metrics import (  # noqa: F401
        DEFAULT_BUCKETS_SECONDS,
        EXTERNAL_METRIC_NAMES,
        Counter,
        Gauge,
        Histogram,
        RequestMetricsMiddleware,
        arq_queue_depth,
        codeguard_quota_429_total,
        codeguard_quota_check_duration_seconds,
        codeguard_quota_drift_rows,
        http_request_duration_seconds,
        http_requests_total,
        render,
    )


# ---------- Histogram buckets ----------


def test_default_buckets_pinned():
    """Pin the bucket boundaries. Every Grafana percentile panel +
    every SLO alert thresholds against these. A drift to looser
    buckets (5ms, 50ms, 500ms, 5s) would silently shift every
    p50/p95/p99 panel's interpretation."""
    from core.metrics import DEFAULT_BUCKETS_SECONDS

    expected = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    assert expected == DEFAULT_BUCKETS_SECONDS, (
        f"DEFAULT_BUCKETS_SECONDS drifted: {DEFAULT_BUCKETS_SECONDS}. "
        "Every Grafana percentile panel + alert rule thresholds "
        "against these exact boundaries; a drift shifts every "
        "rendered percentile silently."
    )


def test_default_buckets_is_tuple_not_list():
    """Tuple = immutable, list = mutable. A list could be `.append()`'d
    by some import-time side effect, silently expanding the bucket
    set without going through review."""
    from core.metrics import DEFAULT_BUCKETS_SECONDS

    assert isinstance(DEFAULT_BUCKETS_SECONDS, tuple), (
        f"DEFAULT_BUCKETS_SECONDS is {type(DEFAULT_BUCKETS_SECONDS).__name__}; "
        "want tuple. A list lets import-time mutation past review."
    )


# ---------- Registered metrics — names + label sets ----------


def test_http_requests_total_label_set():
    """Pin the canonical 3-label set: `method`, `route`, `status`.
    Adding an `org_id` or `user_id` label would explode cardinality
    one-series-per-tenant — Prometheus storage cost climbs linearly,
    Grafana queries slow."""
    from core.metrics import http_requests_total

    assert http_requests_total.name == "http_requests_total"
    assert http_requests_total.label_names == ["method", "route", "status"], (
        f"http_requests_total label_names drifted: "
        f"{http_requests_total.label_names}. The 3-label set is "
        "calibrated against PG storage budgets — adding org_id "
        "explodes cardinality."
    )
    assert http_requests_total.metric_type == "counter"


def test_http_request_duration_seconds_label_set():
    """Same label set as the requests counter — paired so
    `rate(...) by (route)` AND `histogram_quantile(...) by (route)`
    can be joined in a single Grafana query without label-set
    mismatches."""
    from core.metrics import http_request_duration_seconds

    assert http_request_duration_seconds.name == "http_request_duration_seconds"
    assert http_request_duration_seconds.label_names == ["method", "route", "status"], (
        f"http_request_duration_seconds label_names drifted: "
        f"{http_request_duration_seconds.label_names}. Must MATCH "
        "http_requests_total — Grafana joins them by labelset."
    )
    assert http_request_duration_seconds.metric_type == "histogram"


def test_codeguard_quota_429_label_cardinality_bounded():
    """SECURITY/OPS pin. The label set is `["limit_kind"]` only —
    no `org_id`, no `user_id`. A regression that added per-org
    cardinality would explode the series count to thousands once
    the platform scales (the comment in core/metrics.py spells
    out why). The dashboard question this metric answers ('how
    often are we capping out?') doesn't need per-org breakdown.
    """
    from core.metrics import codeguard_quota_429_total

    assert codeguard_quota_429_total.name == "codeguard_quota_429_total"
    assert codeguard_quota_429_total.label_names == ["limit_kind"], (
        f"codeguard_quota_429_total labels drifted: "
        f"{codeguard_quota_429_total.label_names}. Adding org_id "
        "explodes cardinality past the documented 2-value bound. "
        "If you need per-org analysis, query the audit log instead."
    )


def test_codeguard_quota_drift_rows_is_gauge_not_counter():
    """SECURITY/CORRECTNESS pin. The reconcile cron sets this each
    run to the CURRENT count of drift rows. A regression to
    Counter (monotonic-increment-only) would let alerts fire on
    "100 cumulative drift rows ever" instead of "100 drift rows
    RIGHT NOW" — different signal entirely."""
    from core.metrics import codeguard_quota_drift_rows

    assert codeguard_quota_drift_rows.metric_type == "gauge", (
        f"codeguard_quota_drift_rows metric_type is "
        f"{codeguard_quota_drift_rows.metric_type!r}; want gauge. "
        "Counter semantics would let cumulative drift trigger "
        "alerts that 'right-now' drift wouldn't."
    )


def test_arq_queue_depth_has_no_labels():
    """Single-value gauge — no per-queue breakdown. A regression
    that added a `queue_name` label would silently change the
    Grafana panel from 'one line' to 'N lines'."""
    from core.metrics import arq_queue_depth

    assert arq_queue_depth.name == "arq_queue_depth"
    assert arq_queue_depth.label_names == []
    assert arq_queue_depth.metric_type == "gauge"


# ---------- External-name registry ----------


def test_external_metric_names_pinned():
    """The set of metric names emitted OUTSIDE `core.metrics` (by
    `routers/ops.py::_build_metrics_text`). Must stay in lockstep
    with the ops router. The validator script
    (`scripts/validate_prometheus_rules.py`) reads this set to
    resolve alert-rule `expr` references; a drift silently breaks
    the validator."""
    from core.metrics import EXTERNAL_METRIC_NAMES

    expected = frozenset(
        {
            "aec_webhook_deliveries_total",
            "aec_webhook_outbox_lag_seconds",
            "aec_webhook_outbox_pending",
            "aec_api_key_calls_total",
            "aec_search_queries_total",
            "aec_audit_events_total",
        }
    )
    assert expected == EXTERNAL_METRIC_NAMES, (
        f"EXTERNAL_METRIC_NAMES drifted: have {EXTERNAL_METRIC_NAMES}, "
        f"want {expected}. Either routers/ops.py added/removed a "
        "metric (this set MUST move in lockstep) or the validator "
        "script's expectations need updating."
    )


def test_external_metric_names_is_frozenset():
    """Frozen so import-time code can't `.add()` to it."""
    from core.metrics import EXTERNAL_METRIC_NAMES

    assert isinstance(EXTERNAL_METRIC_NAMES, frozenset)


# ---------- Counter behaviour ----------


def test_counter_inc_default_value_is_one():
    """`Counter.inc()` defaults to +1. A regression that defaulted
    to 0 would silently make every `.inc()` a no-op."""
    from core.metrics import Counter

    c = Counter("test_counter", ["lbl"])
    c.inc({"lbl": "x"})
    c.inc({"lbl": "x"})
    c.inc({"lbl": "y"})

    # Two ticks for x, one for y.
    assert c._values[("x",)] == 2
    assert c._values[("y",)] == 1


def test_counter_inc_accepts_custom_value():
    """`.inc(value=N)` ticks by N. Used by the codeguard cap-check
    to record token counts in one tick. A regression that ignored
    the value arg would lose token accounting."""
    from core.metrics import Counter

    c = Counter("test_counter", [])
    c.inc(value=5.0)
    c.inc(value=3.0)
    assert c._values[()] == 8.0


# ---------- Histogram observation ----------


def test_histogram_observe_increments_correct_buckets():
    """A 0.07s observation MUST tick every bucket whose `le >= 0.07`.
    The DEFAULT_BUCKETS_SECONDS at 0.07s: 0.1, 0.25, 0.5, 1.0, 2.5,
    5.0, 10.0 — 7 buckets. The lower 4 buckets (0.005, 0.01, 0.025,
    0.05) MUST NOT tick.
    """
    from core.metrics import DEFAULT_BUCKETS_SECONDS, Histogram

    h = Histogram("test_hist", [])
    h.observe(0.07)

    row = h._observations[()]
    # row[0] = sum, row[1] = count, row[2:] = bucket counts
    assert row[0] == 0.07
    assert row[1] == 1.0

    for i, b in enumerate(DEFAULT_BUCKETS_SECONDS):
        bucket_count = row[2 + i]
        if b >= 0.07:
            assert bucket_count == 1.0, (
                f"Bucket {b}s did not tick on 0.07s observation. Histogram cumulative bucket semantics broken."
            )
        else:
            assert bucket_count == 0.0, (
                f"Bucket {b}s ticked on 0.07s observation when it "
                "should not have. Cumulative bucket semantics inverted."
            )


# ---------- Renderer / exposition format ----------


def test_render_emits_help_and_type_lines():
    """Every metric MUST emit `# HELP <name> <text>` and
    `# TYPE <name> <type>` before its value rows. Prometheus
    parsers tolerate missing HELP/TYPE but Grafana panels lose
    the tooltip text — a small UX regression that's easy to
    miss in code review.
    """
    from core.metrics import render

    text = render()

    assert "# HELP http_requests_total" in text
    assert "# TYPE http_requests_total counter" in text
    assert "# HELP http_request_duration_seconds" in text
    assert "# TYPE http_request_duration_seconds histogram" in text
    assert "# HELP arq_queue_depth" in text
    assert "# TYPE arq_queue_depth gauge" in text


def test_render_emits_codeguard_quota_429_metric():
    """Pin the codeguard cap-check metric is in the exposition.
    The matching Grafana alert rule `expr`s against this exact
    name; absence = silent alert disable."""
    from core.metrics import render

    text = render()
    assert "# HELP codeguard_quota_429_total" in text
    assert "# TYPE codeguard_quota_429_total counter" in text


def test_format_float_avoids_scientific_notation():
    """SECURITY/CORRECTNESS pin. Prometheus's text-format parsers
    accept scientific notation (`5e-3`) but stable string repr is
    important: `0.005` and `5e-3` are the SAME number but produce
    DIFFERENT bucket-label series. A drift across runs would
    fragment the time-series in Prometheus storage.
    """
    from core.metrics import _format_float

    # Whole numbers render as `<n>.0` (the Prometheus convention
    # for integer bucket boundaries).
    assert _format_float(1.0) == "1.0"
    assert _format_float(5.0) == "5.0"

    # Fractions render via `:g` — short-form decimal, no exponent.
    assert "e" not in _format_float(0.005).lower()
    assert "e" not in _format_float(0.025).lower()
    assert _format_float(0.005) == "0.005"


def test_format_labels_escapes_special_chars():
    """Prometheus requires double-quoted label values with `\\`,
    `"`, `\n` escaped. A regression that skipped escaping would
    let a malicious or accidental `"` in a label value break
    every line that follows in the scrape — Prometheus would
    parse-error the whole metric family."""
    from core.metrics import _format_labels

    out = _format_labels(["k"], ('a"b\\c\nd',))
    assert out == '{k="a\\"b\\\\c\\nd"}', (
        f"_format_labels output {out!r} doesn't match expected "
        "Prometheus escape semantics. A bad label value would "
        "break the scrape's parsability."
    )


def test_render_includes_le_inf_bucket_for_histograms():
    """Prometheus histograms MUST include a `le="+Inf"` bucket
    that equals the total observation count. Without it, the
    histogram is malformed and `histogram_quantile()` returns NaN.
    """
    # Observe one sample on the registered http_request_duration
    # histogram so the render path emits a row for it.
    from core.metrics import http_request_duration_seconds as h
    from core.metrics import render

    h.observe(0.05, {"method": "GET", "route": "/test", "status": "200"})

    text = render()
    assert 'le="+Inf"' in text, (
        'Histogram exposition is missing the `le="+Inf"` bucket. '
        "histogram_quantile() returns NaN without it — every "
        "Grafana percentile panel goes blank."
    )


# ---------- Middleware ----------


def test_request_metrics_middleware_uses_route_template():
    """SECURITY/COST pin. The label MUST be the matched route's
    PATH TEMPLATE (e.g. `/api/v1/projects/{project_id}`), NOT the
    literal URL. Otherwise per-UUID cardinality explodes and
    Prometheus storage detonates."""
    import core.metrics as mod

    src = inspect.getsource(mod.RequestMetricsMiddleware)
    assert "_route_template" in src, (
        "RequestMetricsMiddleware no longer routes through "
        "_route_template. The literal path would be used as the "
        "label, exploding cardinality per-UUID."
    )


def test_route_template_helper_falls_back_to_literal_path():
    """For 404s (no route matched), there's no template — fall
    back to the literal path. Defensive: if a regression made the
    helper raise on no-match, every 404 would 500 the metrics
    middleware too."""
    import core.metrics as mod

    # _route_template returns None on no match; the caller decides
    # the fallback. The middleware uses
    # `_route_template(scope) or scope["path"]`. We pin the fallback
    # below — `_route_template`'s own behaviour is exercised by the
    # production code-path it serves.
    middleware_src = inspect.getsource(mod.RequestMetricsMiddleware)
    assert 'scope.get("path"' in middleware_src or 'scope["path"]' in middleware_src, (
        "RequestMetricsMiddleware no longer falls back to "
        'scope["path"] when _route_template returns None. 404s '
        "would now emit a 'None' route label, polluting the metric."
    )


# ---------- Lazy queue-depth probe ----------


def test_sample_queue_depth_uses_negative_one_sentinel_on_failure():
    """SECURITY/CORRECTNESS pin. When the Redis probe fails (Redis
    unreachable), the gauge is set to `-1` — distinct from `0`
    (legit empty queue). Grafana panels render `-1` as 'unknown'
    rather than 'queue is empty'. A regression that emitted `0`
    on failure would let 'broken' masquerade as 'healthy'."""
    import core.metrics as mod

    src = inspect.getsource(mod._sample_queue_depth)
    assert "-1" in src or "-1.0" in src, (
        "_sample_queue_depth no longer sets -1 sentinel on Redis "
        "failure. A `0` on failure would silently make a broken "
        "queue look healthy in Grafana."
    )
    # And the documented behaviour: failure path is best-effort
    # (broad except, not re-raised — gauge update is best-effort).
    assert "except Exception" in src
