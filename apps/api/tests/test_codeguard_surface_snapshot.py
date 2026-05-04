"""Snapshot tests for the codeguard router routes + metrics registry.

Why this exists: across many rounds of work on the quota subsystem,
multiple routes (`/quota/top-users`, `/quota/audit`) and metrics
(`codeguard_quota_drift_rows`, `codeguard_quota_check_cache_total`)
have been added, silently reverted by an aggressive linter / external
process, and re-added — sometimes leaving the frontend referencing
routes that no longer exist on the server. The user only notices
when the widget is broken in production.

This test is the silent-disappearance backstop: it pins the exact
shape of two registries the codeguard surface depends on:

  1. The FastAPI router's `routes` list (URL paths).
  2. `core.metrics._REGISTRY` (Prometheus metric names).

A regression that drops one of these causes a failure here at PR
time, with a clear message ("route X expected but missing"), instead
of shipping a half-built feature.

This is a classic snapshot/contract test: bug-for-bug equivalent to
"if you mean to remove this, update this list AND the consumers."

When adding a new route or metric:
  1. Implement the route/metric in the relevant module.
  2. Add the path/name to the expected set below.
  3. Update the frontend hook / dashboard query that consumes it.
  4. Run this test — it'll fail if any of step 1/3 was missed.
"""

from __future__ import annotations

import pytest

# ---------- Router routes --------------------------------------------------


# Every codeguard route the system depends on, keyed by (method, path).
# Order doesn't matter; this is a set comparison. When you add a route,
# add the entry here.
#
# Path templates use the FastAPI form (`{name}` for path params), NOT
# the regex form Starlette internally uses. We extract the template
# from `route.path` which gives us this shape natively.
_EXPECTED_CODEGUARD_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # Health probe — used by k8s readiness checks.
        ("GET", "/api/v1/codeguard/health"),
        # ---- LLM-invoking routes (every one of these gates on the cap) ----
        ("POST", "/api/v1/codeguard/query"),
        ("POST", "/api/v1/codeguard/query/stream"),
        ("POST", "/api/v1/codeguard/scan"),
        ("POST", "/api/v1/codeguard/scan/stream"),
        ("POST", "/api/v1/codeguard/permit-checklist"),
        ("POST", "/api/v1/codeguard/permit-checklist/stream"),
        # ---- Reads ----
        ("GET", "/api/v1/codeguard/permit-checklist/{checklist_id}/pdf"),
        ("POST", "/api/v1/codeguard/checks/{check_id}/mark-item"),
        ("GET", "/api/v1/codeguard/regulations"),
        ("GET", "/api/v1/codeguard/regulations/{regulation_id}"),
        ("GET", "/api/v1/codeguard/checks/{project_id}"),
        # ---- Quota surface (the load-bearing tenant-facing reads) ----
        # `/quota` — the banner + planning page read this every 60s.
        ("GET", "/api/v1/codeguard/quota"),
        # `/quota/history` — 3-month strip on the planning page.
        ("GET", "/api/v1/codeguard/quota/history"),
        # `/quota/audit` — tenant audit log + CSV export. Reverted
        # twice across rounds before sticking; pin so we catch the
        # next disappearance at PR time.
        ("GET", "/api/v1/codeguard/quota/audit"),
        # `/quota/top-users` — per-user spend ranking for the org's
        # current period. Surfaces `codeguard_user_usage` via the
        # `(org, period, input_tokens DESC)` index. The quota banner
        # page reads this when the usage strip mounts.
        ("GET", "/api/v1/codeguard/quota/top-users"),
    }
)


def _collect_codeguard_routes() -> frozenset[tuple[str, str]]:
    """Walk `routers.codeguard.router.routes` and pull `(method, path)`
    tuples. FastAPI's `APIRoute` carries both as attributes."""
    from routers import codeguard as cg_router

    pairs: set[tuple[str, str]] = set()
    for r in cg_router.router.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path is None or not methods:
            continue
        for m in methods:
            # Skip HEAD/OPTIONS — they're auto-derived from GET, not
            # part of the contract we care about pinning.
            if m in ("HEAD", "OPTIONS"):
                continue
            pairs.add((m, path))
    return frozenset(pairs)


def test_codeguard_router_advertises_expected_routes():
    """Pin the exact set of (method, path) tuples on the codeguard
    router. Both directions matter:

      * EXTRA routes registered → out-of-band route the test set
        doesn't know about. Either add it to the expected set (the
        new feature is intentional) or unregister it (the feature
        was removed but the route lingers, which is a real footgun).

      * MISSING routes → the load-bearing failure mode. A route that
        the frontend depends on has disappeared. Most likely the
        linter / external process reverted the route's definition;
        re-add it. The test message names exactly which route is
        gone so you can `git log -p` for the disappearance.
    """
    actual = _collect_codeguard_routes()

    missing = _EXPECTED_CODEGUARD_ROUTES - actual
    extra = actual - _EXPECTED_CODEGUARD_ROUTES

    if missing:
        pytest.fail(
            "Missing codeguard route(s):\n  "
            + "\n  ".join(f"{m} {p}" for m, p in sorted(missing))
            + "\n\nSomeone (or something) removed this route from "
            "`apps/api/routers/codeguard.py`. The frontend or alert "
            "rules likely still reference it. Either re-add the route "
            "OR remove it from `_EXPECTED_CODEGUARD_ROUTES` here AND "
            "every consumer that targets it."
        )
    if extra:
        # Extras are less load-bearing but still flag-worthy: a stale
        # route the team doesn't realize is exposed could be a security
        # surface (or just dead code). Make the test fail so the
        # author has to add it to the expected set deliberately.
        pytest.fail(
            "Unexpected codeguard route(s) registered:\n  "
            + "\n  ".join(f"{m} {p}" for m, p in sorted(extra))
            + "\n\nIf intentional, add to `_EXPECTED_CODEGUARD_ROUTES`. "
            "If accidental (left over from a deleted feature), "
            "unregister it from the router."
        )


# ---------- Metrics registry -----------------------------------------------


# Every codeguard metric name the alert rules (`infra/prometheus/
# codeguard.alerts.yml`) and dashboards reference. The same set the
# `validate_prometheus_rules.py` validator checks `expr` tokens
# against — pinning here means the registry can't lose a metric
# without the validator AND this test both failing, so the regression
# is impossible to miss.
_EXPECTED_CODEGUARD_METRICS: frozenset[str] = frozenset(
    {
        # Counter — cap-check 429s by binding dimension. Used by the
        # `CodeguardQuotaRefusalSpike` alert rule.
        "codeguard_quota_429_total",
        # Histogram — pre-flight cap-check duration. Used by the
        # `CodeguardQuotaCheckSlow` alert rule (via `_bucket` suffix).
        "codeguard_quota_check_duration_seconds",
        # Gauge — reconcile cron drift signal. Used by the
        # `CodeguardQuotaUsageDrift` alert rule.
        "codeguard_quota_drift_rows",
    }
)


def _collect_codeguard_metrics() -> frozenset[str]:
    """Pull `codeguard_*` metric names from `core.metrics._REGISTRY`.
    Filter to our prefix so future platform-wide metrics (a hypothetical
    `aec_*` series) don't pollute this codeguard-scoped pin."""
    from core import metrics as _metrics

    return frozenset(m.name for m in _metrics._REGISTRY if m.name.startswith("codeguard_"))


def test_codeguard_metrics_registry_advertises_expected_metrics():
    """Pin the exact set of `codeguard_*` metric names. Same
    reasoning as the route snapshot:

      * MISSING metric → the alert rule referencing it silently
        never fires. The validator (`validate_prometheus_rules.py`)
        also catches this, but pinning here flags it earlier in the
        test run.

      * EXTRA metric → either intentional (add to the expected
        set + add an alert rule + dashboard query) or stale dead
        code. Either way, the author should justify it explicitly.
    """
    actual = _collect_codeguard_metrics()

    missing = _EXPECTED_CODEGUARD_METRICS - actual
    extra = actual - _EXPECTED_CODEGUARD_METRICS

    if missing:
        pytest.fail(
            "Missing codeguard metric(s) from core.metrics._REGISTRY:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nA metric referenced by `infra/prometheus/codeguard.alerts.yml` "
            "is missing from the registry. The alert rule will silently never "
            "fire in production. Most likely: someone removed the `_register(...)` "
            "call. Re-register OR drop the alert rule that references it AND "
            "remove from `_EXPECTED_CODEGUARD_METRICS` here."
        )
    if extra:
        pytest.fail(
            "Unexpected codeguard metric(s) registered:\n  "
            + "\n  ".join(sorted(extra))
            + "\n\nIf intentional, add to `_EXPECTED_CODEGUARD_METRICS` AND "
            "wire up an alert rule + dashboard panel. If stale dead code, "
            "remove the `_register(...)` call."
        )


# ---------- Cron jobs ------------------------------------------------------


# Cron jobs the codeguard system depends on. The reconcile cron is the
# only one of these that's ever silently disappeared (mid-revert), but
# pinning the canonical set future-proofs against the same failure
# mode for any cron we add.
_EXPECTED_CODEGUARD_CRONS: frozenset[str] = frozenset(
    {
        # Weekly drift detection between codeguard_org_usage and
        # SUM(codeguard_user_usage). Sets the
        # `codeguard_quota_drift_rows` gauge; alerts fire on
        # sustained nonzero values.
        "codeguard_quota_reconcile_cron",
    }
)


def test_codeguard_cron_jobs_registered():
    """Pin every codeguard-relevant cron job is in
    `WorkerSettings.cron_jobs`. The reconcile cron specifically has
    silently disappeared in past rounds — without it, drift between
    org-level and per-user usage tables accumulates undetected for
    months."""
    try:
        from workers.queue import WorkerSettings
    except ImportError as exc:
        pytest.skip(f"workers.queue not importable in this test env ({exc})")

    crons = WorkerSettings.cron_jobs
    targets = [getattr(c, "coroutine", None) or getattr(c, "func", None) for c in crons]
    target_names = {getattr(t, "__name__", "") for t in targets if t is not None}

    missing = _EXPECTED_CODEGUARD_CRONS - target_names
    if missing:
        pytest.fail(
            "Missing codeguard cron(s) from WorkerSettings.cron_jobs:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nThe cron's coroutine still exists in workers/queue.py "
            "(or it would error on import) but it's not registered in the "
            "schedule. Re-add the `cron(...)` entry."
        )


# ---------- Retention policies --------------------------------------------


# Retention policies for codeguard-owned tables. Pinned in the same
# spirit as the route/metric/cron snapshots: a silent revert that drops
# a policy makes the table unbounded-grow until disk fills up. The pin
# names exactly which policy disappeared so the fix is "re-add this
# entry to RETENTION_POLICIES" not "git log -p the whole file."
_EXPECTED_CODEGUARD_RETENTION_TABLES: frozenset[str] = frozenset(
    {
        # Quota mutation audit log. 730d (2 years) — see the policy
        # docstring in `services/retention.py` for the rationale.
        "codeguard_quota_audit_log",
    }
)


def test_codeguard_retention_policies_registered():
    """Pin every codeguard-owned table that has a retention policy.

    Without this, a removed `RetentionPolicy(...)` entry would let the
    audit log unbounded-grow until ops noticed disk pressure. The
    policy itself is in `services/retention.py` — this test pins
    that the entry survives reformat passes.
    """
    try:
        from services.retention import RETENTION_POLICIES
    except ImportError as exc:
        pytest.skip(f"services.retention not importable in this test env ({exc})")

    actual_tables = {p.table for p in RETENTION_POLICIES}
    missing = _EXPECTED_CODEGUARD_RETENTION_TABLES - actual_tables
    if missing:
        pytest.fail(
            "Missing codeguard retention policy(s) from RETENTION_POLICIES:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nThis table was previously registered for periodic pruning. "
            "Without the policy, it grows unbounded until disk pressure "
            "surfaces in production. Re-add the `RetentionPolicy(...)` "
            "entry in `apps/api/services/retention.py`."
        )
