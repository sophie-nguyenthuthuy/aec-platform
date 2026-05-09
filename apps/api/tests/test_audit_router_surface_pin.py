"""Pin the `routers/audit.py` endpoint surface.

The audit router is the read-side of the compliance log — what
admins use to answer "who did this?" during enterprise security
reviews, customer disputes, and post-incident forensics. Three
invariants this file pins:

  * **Endpoint path stable.** `GET /api/v1/audit/events` is what
    the frontend `useAuditEvents` hook + the `/settings/audit`
    page hit. A rename silently 404s the audit UI and the
    customer-facing "we logged that" promise becomes a lie.

  * **Admin role gate.** `require_min_role(Role.ADMIN)` is the
    discriminator that prevents a regular org member from reading
    cross-team audit content. A regression to `require_auth`
    would expose "Bob demoted Alice" to anyone in the org —
    privacy violation, GDPR exposure for VN PDPL.

  * **Filter param shape.** The query params (`resource_type`,
    `resource_id`, `action`, `actor_kind`, `limit`, `offset`)
    are what `useAuditEvents` passes by name. A rename = the
    frontend silently sends the param under the old name and
    the server's filter ignores it (returns all events instead
    of the filtered subset).

  * **`actor_kind` enum.** Pattern-validated against
    `^(user|api_key|system)$`. A regression that loosened the
    validation would let a partner submit `actor_kind=admin`
    (which the WHERE-clause builder doesn't recognise → no
    filter applied → returns more rows than the caller asked
    for).

  * **Pagination shape.** `limit` is `1..200`, `offset` is `>=0`.
    A regression that allowed `limit=10000` would let the
    audit UI hammer the DB with a 10k-row query; lifting the
    cap would break the indexed-pagination assumption.

This file is read-only — inspects the router's route declarations
and dependency tree without invoking handlers (which would need
a real DB session). Survives reverts of `routers/audit.py`.
"""

from __future__ import annotations

import inspect

# ---------- Module + router presence ----------


def test_audit_router_module_imports():
    """Module + `router` attribute. Hard ImportError on revert =
    desired loud signal."""
    from routers import audit  # noqa: F401
    from routers.audit import router  # noqa: F401


def test_audit_router_attribute():
    """The `router` is what `main.py::create_app` includes.
    Without it, FastAPI startup raises and the API is down."""
    from fastapi import APIRouter

    from routers.audit import router

    assert isinstance(router, APIRouter)


def test_audit_router_prefix_pinned():
    """`/api/v1/audit` is the documented prefix. The frontend's
    `useAuditEvents` hook hardcodes this — rename = 404 on every
    audit-page load."""
    from routers.audit import router

    assert router.prefix == "/api/v1/audit", (
        f"audit router prefix drifted to {router.prefix!r}. The "
        "frontend hardcodes /api/v1/audit; rename has to move both."
    )


# ---------- Endpoint path ----------


def test_events_endpoint_path_pinned():
    """`GET /api/v1/audit/events` is the single read endpoint.
    Frontend `useAuditEvents` hook calls this exact path; a rename
    silently 404s the audit UI."""
    from routers.audit import router

    paths = {r.path for r in router.routes}
    assert "/api/v1/audit/events" in paths, (
        f"audit events endpoint missing; have {paths}. The frontend audit page hardcodes this URL."
    )


def test_events_endpoint_method_is_get_only():
    """Read-only endpoint. The audit log is append-only by design;
    a POST/PUT regression here would either fail at startup OR
    expose mutation routes against an immutable log (catastrophic
    if it slipped through)."""
    from routers.audit import router

    events_route = next(r for r in router.routes if getattr(r, "path", None) == "/api/v1/audit/events")
    methods = set(events_route.methods or [])
    # Allow HEAD (FastAPI auto-adds it for GETs).
    assert methods.issubset({"GET", "HEAD"}), (
        f"/audit/events exposes methods {methods}; want GET-only. "
        "Audit log is append-only — mutation routes here would be "
        "a catastrophic regression."
    )
    assert "GET" in methods


# ---------- Role gate ----------


def test_events_endpoint_admin_gated():
    """SECURITY-CRITICAL pin. Audit events MUST be `require_min_role
    (Role.ADMIN)` gated. A regression to `require_auth` (any logged-
    in user) would expose cross-team audit rows ("Bob demoted Alice
    from admin") to every member — privacy violation under GDPR
    and VN PDPL.

    Pin via source-grep on the handler. A rename of `require_min_role`
    or `Role.ADMIN` would surface the pin failure before the change
    reaches prod.
    """
    import routers.audit as mod

    src = inspect.getsource(mod.list_audit_events)

    assert "require_min_role" in src, (
        "list_audit_events no longer references require_min_role. "
        "A swap to require_auth would expose audit rows to every "
        "logged-in user — privacy regression."
    )
    assert "Role.ADMIN" in src, (
        "list_audit_events no longer gates on Role.ADMIN. The "
        "compliance posture is admin-only; a downgrade to MEMBER "
        "(or removal of the gate) is a privacy regression."
    )


# ---------- Query param shape ----------


def test_events_endpoint_filter_params_pinned():
    """Pin the param names the frontend hook passes. A rename here
    without updating the hook = the hook sends the old name, the
    server ignores it, the response returns ALL events instead of
    the filtered subset (silent over-return)."""
    import routers.audit as mod

    sig = inspect.signature(mod.list_audit_events)
    params = set(sig.parameters.keys())

    expected_query_params = {
        "resource_type",
        "resource_id",
        "action",
        "actor_kind",
        "limit",
        "offset",
    }
    # The handler also has `auth` + `db` (deps) — assert the query
    # params are a subset.
    assert expected_query_params.issubset(params), (
        f"list_audit_events filter params drifted: missing "
        f"{expected_query_params - params}. The frontend hook passes "
        "these by name; renames silently disable the filter."
    )


def test_actor_kind_param_pattern_pinned():
    """SECURITY pin. `actor_kind` MUST be pattern-validated against
    the closed set `(user|api_key|system)`. A regression that
    loosened the pattern would let a partner submit
    `actor_kind=admin` (or any string) — the WHERE-clause builder
    doesn't have a branch for it, so the filter silently no-ops
    and returns ALL rows. Worse: a value like `'; DROP TABLE…`
    would still parse (we use parameterised queries, but the
    pattern is the first line of defence).
    """
    import routers.audit as mod

    # Source-grep is the most stable way to assert the regex pattern —
    # Pydantic's Query metadata stores `pattern` under a Field-internal
    # attribute that's awkward to reach via typing.get_args (Annotated
    # nesting + Pydantic's FieldInfo wrapper). The literal string
    # `^(user|api_key|system)$` in the source is what matters; if it
    # changes, the WHERE-clause builder also has to change.
    src = inspect.getsource(mod.list_audit_events)
    assert 'pattern="^(user|api_key|system)$"' in src or "pattern='^(user|api_key|system)$'" in src, (
        "actor_kind pattern drifted from `^(user|api_key|system)$` in "
        "the source. The handler's WHERE-clause builder only has "
        "branches for these three values; loosening the pattern lets "
        "callers submit unknown values that silently no-op the filter."
    )


def test_limit_bounds_pinned():
    """`limit` is `1..200`. A regression that lifted the upper bound
    to (say) 10_000 would let the audit UI hammer the DB with a
    huge offset+limit query; the underlying index is calibrated for
    the documented range.

    Pin via source-grep — Pydantic's Query() wraps `ge`/`le` deep
    inside a FieldInfo object that's hard to introspect cleanly.
    The literal `Query(default=50, ge=1, le=200)` in the source is
    what matters; a regression to looser bounds shows up here.
    """
    import routers.audit as mod

    src = inspect.getsource(mod.list_audit_events)
    assert "Query(default=50, ge=1, le=200)" in src, (
        "limit Query() bounds drifted from `default=50, ge=1, le=200`. "
        "Lifting le above 200 breaks the pagination assumption (the "
        "index can't efficiently scan past offset~10k). Lowering the "
        "default below 50 changes the audit UI's first-paint."
    )


def test_offset_lower_bound_pinned():
    """`offset >= 0`. A negative offset would either be rejected
    by Postgres OR (worse) silently treated as 0 depending on
    driver — the explicit `ge=0` guard is what makes the
    behaviour deterministic."""
    import routers.audit as mod

    src = inspect.getsource(mod.list_audit_events)
    assert "Query(default=0, ge=0)" in src, (
        "offset Query() bounds drifted from `default=0, ge=0`. "
        "A negative offset's behaviour is driver-dependent without "
        "the explicit ge guard; pin so the contract stays deterministic."
    )


# ---------- Pagination shape ----------


def test_handler_returns_paginated_envelope():
    """The handler MUST go through `paginated()` (not `ok()`) so the
    response carries `meta.{page, per_page, total}`. The frontend's
    pager reads these — a regression to `ok()` would freeze the
    pager on page 1 forever."""
    import routers.audit as mod

    src = inspect.getsource(mod.list_audit_events)
    assert "paginated(" in src, (
        "list_audit_events no longer uses paginated(). The frontend's "
        "pager reads meta.{page,per_page,total} — without those, "
        "navigation between pages stops working."
    )


def test_handler_computes_total_count():
    """The `total` count powers the pager's "X of Y" label. A
    regression that reported the per-page count instead would
    show "50 of 50" forever even with thousands of audit rows
    behind the cursor."""
    import routers.audit as mod

    src = inspect.getsource(mod.list_audit_events)
    # Two natural patterns for total: `count(*)` SQL or a separate
    # counting query. Source-grep for either.
    assert "count(*)" in src or "COUNT(*)" in src, (
        "list_audit_events no longer issues a count(*) for pagination "
        "metadata. The frontend pager would show the per-page count "
        "as the total."
    )


# ---------- WHERE-clause builder shape ----------


def test_handler_filters_by_organization_id():
    """SECURITY-CRITICAL pin. The audit log is per-tenant — every
    query MUST filter by `auth.organization_id`. A regression that
    dropped this filter would expose every other tenant's audit
    rows to any admin (cross-tenant leak via the audit endpoint).

    The actual WHERE clause was extracted into `_build_where` so
    the JSON list endpoint and the CSV export stay in lock-step.
    This test follows the refactor: it verifies the end-to-end
    invariant ("the org filter is wired through to SQL with
    auth.organization_id as the source") by checking BOTH the
    builder's body AND the handler's delegation.
    """
    import routers.audit as mod

    # Layer 1: the SQL builder produces the filter clause.
    builder_src = inspect.getsource(mod._build_where)
    assert "organization_id = :org" in builder_src or "organization_id =:org" in builder_src, (
        "_build_where no longer emits `organization_id = :org`. "
        "Cross-tenant audit-row leak via the admin audit endpoint — "
        "the worst-class regression possible on this surface."
    )

    # Layer 2: the handler delegates with auth.organization_id as
    # the bound value (NOT a query param the caller controls —
    # that would defeat RLS even with the filter present).
    handler_src = inspect.getsource(mod.list_audit_events)
    assert "_build_where(" in handler_src and "organization_id=auth.organization_id" in handler_src, (
        "list_audit_events no longer calls `_build_where(...)` with "
        "`organization_id=auth.organization_id`. If the org filter "
        "comes from a caller-supplied param instead, an admin could "
        "query another tenant's audit log by passing a different "
        "org id."
    )

    # Layer 3 (belt-and-suspenders): the handler's SQL templates
    # interpolate `where_sql` from the builder. A future refactor
    # that bypassed the helper would also pass layers 1+2 but
    # silently emit unfiltered SQL.
    assert "WHERE {where_sql}" in handler_src, (
        "list_audit_events no longer interpolates `where_sql` from "
        "_build_where into its SQL templates. Filter could be built "
        "but never bound — verify the WHERE clause flows end-to-end."
    )


def test_handler_resource_filter_supports_drill_down():
    """The "this object's history" view depends on filtering by
    `resource_type` + `resource_id` together. The frontend uses
    these to build the per-resource audit drilldown — a regression
    that dropped either silently breaks the drill-down."""
    import routers.audit as mod

    sig = inspect.signature(mod.list_audit_events)
    assert "resource_type" in sig.parameters
    assert "resource_id" in sig.parameters

    # And the WHERE clause references both. After the
    # _build_where refactor, the SQL fragments live in the
    # builder rather than the handler — same end-to-end
    # invariant, just one helper hop down.
    builder_src = inspect.getsource(mod._build_where)
    assert "resource_type = :rtype" in builder_src
    assert "resource_id = :rid" in builder_src
