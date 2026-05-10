"""retention_overrides — add RLS policy

Migration 0046 created `retention_overrides` (a tenant-bearing
table — `organization_id` is part of the composite PK) but
shipped without the `ENABLE ROW LEVEL SECURITY` + `CREATE POLICY`
block that the convention in `docs/runbook-rls-policies.md`
requires. The `test_rls_policy_coverage_audit.py` audit caught
the gap.

This migration is the strictly-additive forward fix:

  1. `ALTER TABLE retention_overrides ENABLE ROW LEVEL SECURITY`
  2. `CREATE POLICY tenant_isolation_retention_overrides ON
     retention_overrides USING (...)`

After this migration runs, every read / mutation against
`retention_overrides` filters on `current_setting('app.current_org_id', true)::uuid`
the same way every other tenant-bearing table does.

The reason for a follow-up migration rather than editing 0046
in place: 0046 may already have been applied in some
environments. Editing the upgrade() body wouldn't re-run on
already-stamped DBs, leaving the RLS missing in prod.
A follow-up migration runs unconditionally on the next deploy.

Revision ID: 0048_retention_overrides_rls
Revises: 0047_audit_pins
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op

revision = "0048_retention_overrides_rls"
down_revision = "0047_audit_pins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retention_overrides ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_retention_overrides ON retention_overrides "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_retention_overrides "
        "ON retention_overrides"
    )
    op.execute("ALTER TABLE retention_overrides DISABLE ROW LEVEL SECURITY")
