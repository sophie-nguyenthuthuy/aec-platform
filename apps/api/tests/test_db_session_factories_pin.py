"""Pin the two session factories in `db.session`.

The two factories model two fundamentally different security
postures:

  * **`SessionFactory`** — binds to `database_url` (the NOBYPASSRLS
    `aec_app` role in compose). Every query is RLS-scoped: a SELECT
    for the wrong tenant returns ZERO rows silently. This is the
    factory request-handling code paths use, gated by
    `TenantAwareSession` / `tenant_session()` to set `app.current_org_id`
    so the policies actually evaluate.

  * **`AdminSessionFactory`** — binds to `database_url_admin` (the
    `aec` superuser in compose, BYPASSRLS). Used by:
      - `services.price_alerts.evaluate_price_alerts` — needs every
        alert across every tenant.
      - `services.bidradar_jobs.scrape_and_score_for_all_orgs`
      - `workers.queue.weekly_report_cron`
      - `services.ops_alerts._resolve_drift_recipients`
      - `services.slack_telemetry.record_delivery_attempt` (new)
      - `routers.admin.*` + `routers.slack_deliveries.*` — read-only
        admin telemetry endpoints, gated server-side by
        `require_role("admin")`.

If a refactor swapped the two — `SessionFactory = AdminSessionFactory`
or vice versa — the failure modes are catastrophic and silent:

  * Swap A (`SessionFactory` becomes BYPASSRLS): every tenant's
    request handler now sees every other tenant's data. Single
    worst data-leak vector in the codebase. Nothing throws; tests
    pass; the leak only becomes visible when a customer says
    "why am I seeing project X from another company."

  * Swap B (`AdminSessionFactory` becomes RLS-scoped): every cron
    job silently returns zero rows. Drift alerts stop firing.
    Weekly digest emails go empty. Bidradar stops scoring.
    Nothing throws; logs look fine; ops only learns when the
    next "where are my alerts" ticket arrives.

This file is a read-only contract pin. It survives reverts because
`tests/` is not a known revert target; if either factory ever flips
identity or disappears, this test goes RED.

Pinned contracts:

  * Both factories exist + are `async_sessionmaker`s.
  * Each binds to a DISTINCT engine (a "they got merged into one"
    regression is the headline failure mode).
  * `AdminSessionFactory` MUST point at `database_url_admin` when
    that env var is set — the prod-deploy-without-admin-url path
    is allowed to fall back, but the fallback MUST be flagged.
  * `TenantAwareSession` is constructed from the RLS-scoped factory,
    NOT the admin one. (The whole point of TenantAwareSession is the
    GUC-based RLS scoping; using AdminSessionFactory through it would
    set the GUC but the BYPASSRLS role would ignore the policies and
    leak cross-tenant data anyway.)
"""

from __future__ import annotations

import inspect


def test_both_factories_present():
    """A revert that deleted one of the factories would surface here
    as a hard ImportError. That's the desired signal — better than
    every cron silently 500'ing on first hit."""
    from db.session import AdminSessionFactory, SessionFactory  # noqa: F401


def test_factories_are_async_sessionmakers():
    """Both factories MUST be `async_sessionmaker`s (not
    `sessionmaker`, not `scoped_session`, not a plain function).
    A regression to a sync factory in either slot would deadlock
    every async caller on first session checkout."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.session import AdminSessionFactory, SessionFactory

    assert isinstance(SessionFactory, async_sessionmaker), (
        f"SessionFactory is {type(SessionFactory).__name__}; want async_sessionmaker."
    )
    assert isinstance(AdminSessionFactory, async_sessionmaker), (
        f"AdminSessionFactory is {type(AdminSessionFactory).__name__}; want async_sessionmaker."
    )


def test_factories_bind_to_distinct_engines():
    """SECURITY-CRITICAL pin. The whole point of having two factories
    is that they bind to two different DB roles (NOBYPASSRLS vs
    BYPASSRLS). A "consolidation" refactor that pointed both at
    the same engine would either:

      * Leak cross-tenant data via every request handler (admin
        engine in the user-facing slot), or
      * Silently zero-out every cron job (user engine in the admin
        slot).

    Either way, nothing throws, no test fails by default — the
    only observable signal is "data is wrong." Pin the discriminator
    explicitly so a future engine merge breaks loudly here.
    """
    from db.session import AdminSessionFactory, SessionFactory

    # `async_sessionmaker.kw["bind"]` exposes the bound engine.
    user_engine = SessionFactory.kw.get("bind")
    admin_engine = AdminSessionFactory.kw.get("bind")

    assert user_engine is not None, "SessionFactory has no bound engine — sessions will be unusable."
    assert admin_engine is not None, "AdminSessionFactory has no bound engine — cron jobs will be unusable."

    # When `database_url_admin` is set, the engines MUST be distinct.
    # In the local-dev fallback path (admin url unset → reuse user
    # url), this assertion would be intentionally relaxed — but the
    # pin still catches the "merged into one symbol" refactor where
    # `AdminSessionFactory = SessionFactory`.
    from core.config import get_settings

    settings = get_settings()
    if settings.database_url_admin:
        assert user_engine is not admin_engine, (
            "Both factories bound to the same engine. If `database_url_admin` "
            "is set, the factories MUST bind to distinct engines — a 'merge' "
            "refactor here is the cross-tenant leak vector."
        )

    # Even in the fallback path, the FACTORIES themselves MUST be
    # distinct objects. `AdminSessionFactory = SessionFactory` would
    # break the future-proofing of the admin-url branch (the admin
    # path would silently never engage even after the env var lands).
    assert SessionFactory is not AdminSessionFactory, (
        "SessionFactory and AdminSessionFactory are the same object — "
        "future setting of `database_url_admin` would silently no-op."
    )


def test_admin_session_factory_uses_admin_url_when_configured():
    """Pin: when the `database_url_admin` setting is populated, the
    AdminSessionFactory's engine URL matches it (modulo asyncpg/SQL
    URL representations). A regression that ignored the env var
    would leave production crons running RLS-scoped — silent zero-row
    returns for every cross-tenant query.
    """
    from core.config import get_settings
    from db.session import AdminSessionFactory

    settings = get_settings()
    if not settings.database_url_admin:
        # Local-dev fallback path; pin doesn't apply.
        return

    bound_engine = AdminSessionFactory.kw["bind"]
    # `str(engine.url)` masks the password as `***`; `render_as_string`
    # with `hide_password=False` returns the URL the engine actually
    # opens against, which is what we need to compare to the raw env
    # value in `settings.database_url_admin`.
    bound_url = bound_engine.url.render_as_string(hide_password=False)

    # The URL representations differ (asyncpg vs sync drivers,
    # password-masking, etc.) so we compare host + database parts
    # which are the security-relevant bits.
    expected = settings.database_url_admin

    # Normalise both sides — strip the `postgresql+asyncpg://` prefix
    # if either side is missing it, then compare the suffix.
    def _suffix(u: str) -> str:
        return u.split("://", 1)[-1]

    assert _suffix(expected).rstrip("/") in _suffix(bound_url).rstrip("/") or (
        _suffix(bound_url).rstrip("/") in _suffix(expected).rstrip("/")
    ), (
        f"AdminSessionFactory engine URL ({bound_url!r}) doesn't match "
        f"settings.database_url_admin ({expected!r}); cron jobs would "
        "run RLS-scoped instead of BYPASSRLS."
    )


def test_tenant_aware_session_uses_rls_scoped_factory():
    """`TenantAwareSession.__aenter__` constructs sessions via
    `SessionFactory()` — NOT `AdminSessionFactory()`. Pin the
    source so a "fix the cross-tenant problem by always using
    admin" refactor here would break loudly.

    The whole point of TenantAwareSession is that it sets the
    `app.current_org_id` GUC and lets RLS policies enforce
    isolation. Constructing via AdminSessionFactory would set
    the GUC, but the BYPASSRLS role would ignore policies and
    expose cross-tenant data anyway.
    """
    import db.session as session_mod

    src = inspect.getsource(session_mod.TenantAwareSession.__aenter__)
    assert "SessionFactory()" in src, (
        "TenantAwareSession.__aenter__ no longer constructs via SessionFactory(). "
        "If it now uses AdminSessionFactory(), every request that goes through "
        "tenant_session() would BYPASSRLS — single biggest cross-tenant leak vector."
    )
    assert "AdminSessionFactory()" not in src, (
        "TenantAwareSession.__aenter__ uses AdminSessionFactory() — the BYPASSRLS "
        "role would ignore RLS policies, leaking cross-tenant data."
    )


def test_tenant_session_helper_present():
    """`tenant_session(org_id)` is the asynccontextmanager façade
    around TenantAwareSession used by request handlers. A revert
    that dropped it would break every router that uses it as
    `async with tenant_session(...) as db:`."""
    from db.session import tenant_session

    # MUST be an async-context-manager (the @asynccontextmanager
    # decorator wraps the underlying async generator).
    assert callable(tenant_session)
    assert hasattr(tenant_session, "__wrapped__") or hasattr(
        tenant_session("00000000-0000-0000-0000-000000000000"),  # type: ignore[arg-type]
        "__aenter__",
    ), "tenant_session is not an async context manager"
