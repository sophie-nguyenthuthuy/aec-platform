"""Stdlib Prometheus metrics — counters, histograms, gauges, and a
text-exposition renderer.

Why not `prometheus_client`: we expose three metric families and need
no exotic features (multiprocess mode, push gateway, etc.). A 100-line
home-grown module avoids the SDK + its transitive deps and gives us
a smaller surface to audit.

Concurrency: the in-memory counters are mutated under a single
`threading.Lock`. Postgres-style atomic increments would let us scale
to high concurrency, but that's premature — at our request volumes
the lock is cheap and never contended.

What's instrumented today:
  * `http_requests_total{method, route, status}` — counter, one tick
    per inbound request, fired from `RequestMetricsMiddleware`.
  * `http_request_duration_seconds_bucket{...}` — histogram of
    end-to-end request latency, same labelset.
  * `arq_queue_depth` — gauge sampled lazily on `/metrics` GET. The
    sample is best-effort; a Redis hiccup turns into the gauge being
    `nan` rather than the endpoint 500'ing.

Adding a new metric is a two-liner: `m = Counter("name", ["lbl"])`
in this module + `m.inc({"lbl": ...})` at the call site.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable

# ---------- Primitive metric classes ----------


class _LabelledMap:
    """Thread-safe `dict[tuple, float]` keyed by sorted label values.

    Subclasses define what `inc` / `observe` mean. Centralising the
    locking + label tuple math here keeps each metric class tiny.
    """

    def __init__(self, name: str, label_names: list[str], help_text: str = "") -> None:
        self.name = name
        self.label_names = label_names
        self.help_text = help_text
        self._values: dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()

    def _key(self, labels: dict[str, str] | None) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(n, "") for n in self.label_names)


class Counter(_LabelledMap):
    """Monotonic count. Reset only on process restart."""

    metric_type = "counter"

    def inc(self, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            self._values[self._key(labels)] += value


class Gauge(_LabelledMap):
    """Point-in-time value. Useful for "queue depth" / "active sessions"."""

    metric_type = "gauge"

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._values[self._key(labels)] = value


# Default histogram buckets in seconds. Covers everything from sub-ms
# health checks to multi-second AI-pipeline calls. Keep the count
# small — every bucket × every label combo is a series.
DEFAULT_BUCKETS_SECONDS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


class Histogram(_LabelledMap):
    """Observation buckets + sum + count. Renders as
    `<name>_bucket{le="..."}`, `<name>_sum`, `<name>_count`."""

    metric_type = "histogram"

    def __init__(
        self,
        name: str,
        label_names: list[str],
        help_text: str = "",
        buckets: tuple[float, ...] = DEFAULT_BUCKETS_SECONDS,
    ) -> None:
        super().__init__(name, label_names, help_text)
        self.buckets = buckets
        # Each label-tuple key holds (sum, count, [bucket_counts]).
        self._observations: dict[tuple, list[float]] = {}

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._key(labels)
        with self._lock:
            if key not in self._observations:
                self._observations[key] = [0.0, 0.0] + [0.0] * len(self.buckets)
            row = self._observations[key]
            row[0] += value  # sum
            row[1] += 1.0  # count
            for i, b in enumerate(self.buckets):
                if value <= b:
                    row[2 + i] += 1.0


# ---------- Module-level registry ----------

_REGISTRY: list = []


def _register(metric):
    _REGISTRY.append(metric)
    return metric


http_requests_total = _register(
    Counter(
        "http_requests_total",
        ["method", "route", "status"],
        help_text="Count of inbound HTTP requests.",
    )
)
http_request_duration_seconds = _register(
    Histogram(
        "http_request_duration_seconds",
        ["method", "route", "status"],
        help_text="End-to-end inbound HTTP request latency.",
    )
)
arq_queue_depth = _register(
    Gauge(
        "arq_queue_depth",
        [],
        help_text="Pending jobs in the arq Redis queue. -1 if Redis is unreachable.",
    )
)

# ---------- Codeguard cap-check ----------
#
# `codeguard_quota_429_total` ticks once per inbound LLM-route request
# that the cap-check refused. `limit_kind` is "input" or "output" — the
# binding dimension on the failing org's row. Cardinality is bounded
# (2 values) so this is safe to leave on every route.
#
# We deliberately don't add an `org_id` label here. Per-org cardinality
# would explode the series count to thousands once the platform scales,
# and the dashboard question this metric answers ("how often are we
# capping out tenants?") doesn't need per-org breakdown — that's what
# the audit log + the /quota page are for. If a future runbook wants
# "which orgs cap most," query the audit log, not Prometheus.
#
# `codeguard_quota_check_duration_seconds` wraps the SELECT used by
# every LLM route's pre-flight. Pinning latency here is what lets ops
# answer "did adding the cap-check inflate p95 across the platform?"
# without running a separate benchmark — the existing scrape gives
# them the histogram for free.
codeguard_quota_429_total = _register(
    Counter(
        "codeguard_quota_429_total",
        ["limit_kind"],
        help_text="Cap-check 429s by binding dimension (input|output).",
    )
)
codeguard_quota_check_duration_seconds = _register(
    Histogram(
        "codeguard_quota_check_duration_seconds",
        [],
        help_text="Pre-flight cap-check (SELECT) duration on every LLM route.",
    )
)
# Reconcile cron drift signal. Set per-run by
# `codeguard_quota_reconcile_cron` to the count of (org, period) rows
# where `codeguard_org_usage` totals diverge from
# `SUM(codeguard_user_usage)` by more than 1000 tokens. Why a Gauge
# not a Counter: we want "how many drift rows RIGHT NOW," not "how
# many ever detected" — `CodeguardQuotaUsageDrift` alerts on a
# sustained nonzero value, not a rate. Set to 0 explicitly on a clean
# run so dashboards distinguish "clean" from "metric never published."
codeguard_quota_drift_rows = _register(
    Gauge(
        "codeguard_quota_drift_rows",
        [],
        help_text="(org, period) row count from the most recent reconcile cron run.",
    )
)


# ---------- Renderer ----------


def _format_labels(label_names: list[str], values: tuple) -> str:
    if not label_names:
        return ""
    pairs = []
    for n, v in zip(label_names, values, strict=True):
        # Prometheus requires double-quoted values with `\\`, `"`, `\n`
        # escaped. Stdlib `str.translate` is fastest for the small set.
        escaped = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        pairs.append(f'{n}="{escaped}"')
    return "{" + ",".join(pairs) + "}"


def render() -> str:
    """Render the registry in Prometheus 0.0.4 text exposition format.

    Snapshot taken under each metric's lock so a render doesn't see a
    half-applied increment. The lock is held only long enough to copy
    the dict — never across the (potentially slow) string-formatting.
    """
    out: list[str] = []
    for m in _REGISTRY:
        out.append(f"# HELP {m.name} {m.help_text}")
        out.append(f"# TYPE {m.name} {m.metric_type}")

        if isinstance(m, Histogram):
            with m._lock:
                snapshot = {k: list(v) for k, v in m._observations.items()}
            for key, row in snapshot.items():
                _sum, _count = row[0], row[1]
                # `observe()` ticks every bucket whose `le` >= the value,
                # so `row[2+i]` is already the cumulative `<= bucket[i]`
                # count. No re-derivation needed at render time.
                for i, b in enumerate(m.buckets):
                    labels = dict(zip(m.label_names, key, strict=True))
                    labels["le"] = _format_float(b)
                    label_str = _format_labels(list(labels.keys()), tuple(labels.values()))
                    out.append(f"{m.name}_bucket{label_str} {row[2 + i]}")
                # `+Inf` bucket = total count.
                inf_labels = dict(zip(m.label_names, key, strict=True))
                inf_labels["le"] = "+Inf"
                out.append(
                    f"{m.name}_bucket{_format_labels(list(inf_labels.keys()), tuple(inf_labels.values()))} {_count}"
                )
                out.append(f"{m.name}_sum{_format_labels(m.label_names, key)} {_sum}")
                out.append(f"{m.name}_count{_format_labels(m.label_names, key)} {_count}")
        else:
            with m._lock:
                snapshot = dict(m._values)
            if not snapshot:
                # Render a single zero-row so scrapers see the metric exists.
                # For labelled metrics with no observations there's no canonical
                # label tuple to render under, so the `# HELP`/`# TYPE` lines
                # alone announce existence and we skip the value row.
                if not m.label_names:
                    out.append(f"{m.name} 0")
            else:
                for key, value in snapshot.items():
                    out.append(f"{m.name}{_format_labels(m.label_names, key)} {value}")
    return "\n".join(out) + "\n"


def _format_float(v: float) -> str:
    """Stable string repr of a bucket boundary. Avoids `0.005` vs `5e-3`
    drift across runs (Prometheus parsers are strict-ish)."""
    if v == int(v):
        return f"{int(v)}.0"
    return f"{v:g}"


# ---------- Middleware ----------


class RequestMetricsMiddleware:
    """ASGI middleware that ticks `http_requests_total` and observes
    request duration on every request.

    Uses the matched route's `path` (e.g. `/api/v1/projects/{project_id}`)
    as the label, NOT the literal URL — otherwise label cardinality
    explodes per-UUID and Prometheus storage detonates.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        start = time.perf_counter()
        status_holder: dict[str, int] = {"code": 0}

        async def _send(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed = time.perf_counter() - start
            method = scope.get("method", "")
            route = _route_template(scope) or scope.get("path", "")
            status = str(status_holder["code"] or 0)
            labels = {"method": method, "route": route, "status": status}
            http_requests_total.inc(labels)
            http_request_duration_seconds.observe(elapsed, labels)


def _route_template(scope) -> str | None:
    """Extract the matched route's path template from the FastAPI/Starlette
    scope. Falls back to the literal path if no route matched (404)."""
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    return None


# ---------- Lazy queue-depth probe ----------


async def _sample_queue_depth() -> None:
    """Best-effort arq queue-depth sample. Called on every `/metrics` GET
    so the gauge reflects the current state without a separate cron.

    We tolerate a Redis hiccup by setting the gauge to -1 — that's a
    sentinel a Grafana panel can render as 'unknown' rather than 0
    (which would falsely mean 'queue is empty')."""
    try:
        from arq.connections import RedisSettings, create_pool

        from core.config import get_settings

        settings = get_settings()
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            depth = await pool.zcard("arq:queue")
            arq_queue_depth.set(float(depth))
        finally:
            closer: Callable | None = getattr(pool, "aclose", None) or getattr(pool, "close", None)
            if closer is not None:
                await closer()
    except Exception:  # noqa: BLE001 — gauge update is best-effort
        arq_queue_depth.set(-1.0)
