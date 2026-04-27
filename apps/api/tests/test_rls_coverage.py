"""Cross-module RLS coverage sweep.

Locks in the platform-wide invariant: every table with an
`organization_id` column has RLS enabled and a `tenant_isolation_*`
policy. This catches the classic mistake of adding a model with the
right column but forgetting the migration's `ALTER TABLE … ENABLE ROW
LEVEL SECURITY` block — a regression no per-vertical test would
catch because the table looks correct from the application code.

Skipped unless `COSTPULSE_RLS_DB_URL` is set (same gate as
`test_costpulse_rls.py`); a live DB at migration head is required to
read `pg_tables` / `pg_policies`.

Allowlist: the few tables that *legitimately* lack RLS — `users`,
`organizations`, `org_members` — are global by design, not tenant-
scoped. They live above the RLS layer and are guarded at the
application level (e.g. `me.py` only writes `users` rows for the
JWT subject).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_DB_URL = os.environ.get("COSTPULSE_RLS_DB_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not _DB_URL,
        reason="RLS coverage sweep needs COSTPULSE_RLS_DB_URL pointing at a live DB.",
    ),
]


# Tables that legitimately have an `organization_id` column (or live in
# `public` without one) but should NOT be RLS-scoped. Each entry needs a
# rationale — adding a table here is a cross-tenant decision and should
# not be done casually.
_ALLOWLIST: dict[str, str] = {
    # Identity primitives — global. RLS would chicken-and-egg the
    # auth middleware (lookup user → check membership).
    "organizations": "global identity table; no organization_id",
    "users": "global identity table; no organization_id",
    "org_members": (
        "join table read by `me.py` via AdminSessionFactory. Tenant filtering "
        "happens application-side because the auth path needs to enumerate a "
        "user's orgs *before* an org GUC can be set."
    ),
    # Alembic bookkeeping.
    "alembic_version": "alembic internal",
    # Global ops telemetry — no tenant scope.
    "scraper_runs": "global ops telemetry; see migration 0012_scraper_runs",
    # Reference data shared across tenants by design (codeguard regs etc.).
    "regulations": "global reference catalogue (QCVN, IBC, …)",
    "regulation_chunks": "global reference catalogue chunks",
    # Material-price cross-tenant table — see 0002_costpulse for the
    # rationale (one supplier price feeds many tenants).
    "material_prices": "shared price catalogue; no organization_id by design",
}


@pytest.fixture
async def admin_session():
    """Read-only session as the migration role — needs `pg_policies` access."""
    assert _DB_URL is not None
    engine = create_async_engine(_DB_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_every_org_scoped_table_has_rls_enabled(admin_session):
    """Each `public.*` table with an `organization_id` must have RLS on.

    Reads the live DB schema directly so this catches drift between
    the model layer (`organization_id: Mapped[UUID] = mapped_column(...)`)
    and the migration layer (`ENABLE ROW LEVEL SECURITY`). One without
    the other is the bug shape this test exists to prevent.
    """
    org_scoped = (
        (
            await admin_session.execute(
                text(
                    """
                SELECT c.table_name
                FROM information_schema.columns c
                JOIN information_schema.tables t USING (table_schema, table_name)
                WHERE c.table_schema = 'public'
                  AND c.column_name = 'organization_id'
                  AND t.table_type = 'BASE TABLE'
                """
                )
            )
        )
        .scalars()
        .all()
    )

    rls_tables = set(
        (
            await admin_session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND rowsecurity")
            )
        )
        .scalars()
        .all()
    )

    missing = [tbl for tbl in org_scoped if tbl not in rls_tables and tbl not in _ALLOWLIST]
    assert not missing, (
        f"Tables with organization_id but no RLS enabled: {sorted(missing)}. "
        "Either add `ALTER TABLE … ENABLE ROW LEVEL SECURITY` to the relevant "
        "migration, or add an entry to `_ALLOWLIST` with a justification."
    )


async def test_every_rls_enabled_table_has_a_tenant_isolation_policy(admin_session):
    """RLS without a policy = `SELECT` returns zero rows for everyone.

    Forgetting the policy after enabling RLS is a near-miss waiting to
    happen — the `aec_app` role would silently see no data and the
    dashboard would render empty. We pin: every public table with RLS
    on must have at least one USING-policy.
    """
    rows = (
        await admin_session.execute(
            text(
                """
                SELECT t.tablename, COUNT(p.policyname) AS policy_count
                FROM pg_tables t
                LEFT JOIN pg_policies p
                       ON p.schemaname = t.schemaname AND p.tablename = t.tablename
                WHERE t.schemaname = 'public' AND t.rowsecurity
                GROUP BY t.tablename
                """
            )
        )
    ).all()

    missing = [tbl for tbl, count in rows if count == 0]
    assert not missing, (
        f"Tables with RLS enabled but NO policy attached: {sorted(missing)}. "
        "Add a `CREATE POLICY tenant_isolation_<table> ON <table> USING "
        "(organization_id = current_setting('app.current_org_id', true)::uuid)`."
    )
