"""Add `WITH CHECK` to every tenant-isolation RLS policy

Audit finding: of 58 tenant-scoped tables on the platform, only 3
(`project_watches`, `assistant_threads`, `invitations` after
0018) had `WITH CHECK` clauses on their RLS policies. The other 55
all had `USING (...)` only.

The gap: a `USING` predicate filters which rows a query SEES. A
`WITH CHECK` predicate is what blocks INSERT / UPDATE from creating
a row whose `organization_id` doesn't match the caller's GUC. Without
it, an authenticated user — even a low-privilege `member` or `viewer`
— could:

    INSERT INTO change_orders (organization_id, ...) VALUES
        ('<other-tenant-uuid>', ...);

The row is created in the target tenant. The inserter can't SELECT
it back (USING blocks that), but the row is *real* — it shows up in
the target's dashboards, count queries, downstream cron jobs, etc.

This migration walks `pg_policy`, finds every policy whose
`polwithcheck IS NULL` AND whose name starts with `tenant_isolation_`
(or `tenant_visibility_` for the legacy supplier table), and re-creates
it with `WITH CHECK` matching the existing `USING` expression. Doing
it in PL/pgSQL keeps the migration short and resilient to
table-by-table differences (some policies join through other tables;
copying the `USING` verbatim works for all shapes).

Revision ID: 0021_rls_with_check_everywhere
Revises: 0020_punchlist, 0019_activity_feed_indexes
Create Date: 2026-04-27

Doubles as the merge point for `0020_punchlist` (a parallel-session
migration that landed off `0019_activity_feed_indexes` while this
audit was in flight). Carrying real DDL on a merge revision is
supported by Alembic — the merge semantics come from the
`down_revision` tuple, the upgrade itself runs the policy fixes.
"""

from __future__ import annotations

from alembic import op


revision = "0021_rls_with_check_everywhere"
down_revision = ("0020_punchlist", "0019_activity_feed_indexes")
branch_labels = None
depends_on = None


# Plpgsql block — for each tenant_isolation_* / tenant_visibility_*
# policy missing WITH CHECK, drop and recreate with the same expression
# in both USING and WITH CHECK slots. Schema-qualifying with
# `polrelid::regclass` keeps it independent of the public schema name.
_FIX_RLS_SQL = """
DO $$
DECLARE
    rec RECORD;
    using_expr TEXT;
BEGIN
    FOR rec IN
        SELECT polrelid::regclass::text AS tbl,
               polname,
               pg_get_expr(polqual, polrelid) AS expr
        FROM pg_policy
        WHERE polwithcheck IS NULL
          AND (polname LIKE 'tenant_isolation_%' OR polname LIKE 'tenant_visibility_%')
    LOOP
        EXECUTE format('DROP POLICY %I ON %s', rec.polname, rec.tbl);
        EXECUTE format(
            'CREATE POLICY %I ON %s USING (%s) WITH CHECK (%s)',
            rec.polname, rec.tbl, rec.expr, rec.expr
        );
        RAISE NOTICE 'Policy %.%: added WITH CHECK', rec.tbl, rec.polname;
    END LOOP;
END
$$;
"""


# Best-effort downgrade — drops the WITH CHECK clauses by recreating
# without them. We can't tell which policies were originally missing
# WITH CHECK without the original migrations, so the downgrade just
# removes WITH CHECK from EVERY tenant_isolation_* / tenant_visibility_*
# policy. Acceptable: the only reason to downgrade is to roll back
# this migration on the same DB it was applied to.
_REVERT_RLS_SQL = """
DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT polrelid::regclass::text AS tbl,
               polname,
               pg_get_expr(polqual, polrelid) AS expr
        FROM pg_policy
        WHERE polwithcheck IS NOT NULL
          AND (polname LIKE 'tenant_isolation_%' OR polname LIKE 'tenant_visibility_%')
    LOOP
        EXECUTE format('DROP POLICY %I ON %s', rec.polname, rec.tbl);
        EXECUTE format(
            'CREATE POLICY %I ON %s USING (%s)',
            rec.polname, rec.tbl, rec.expr
        );
    END LOOP;
END
$$;
"""


def upgrade() -> None:
    op.execute(_FIX_RLS_SQL)


def downgrade() -> None:
    op.execute(_REVERT_RLS_SQL)
