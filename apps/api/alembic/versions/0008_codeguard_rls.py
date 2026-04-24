"""enable RLS on codeguard tenant-scoped tables

Missed in 0005_codeguard. The router explicitly filters every read by
organization_id, but sibling modules (pulse, costpulse, winwork, bidradar)
defend in depth with a `tenant_isolation_*` policy backed by
`current_setting('app.current_org_id')`. This migration brings
compliance_checks and permit_checklists in line with that convention.

`regulations` and `regulation_chunks` remain un-scoped — they're global
reference data (QCVN codes, IBC, etc.) shared across tenants by design.

Revision ID: 0008_codeguard_rls
Revises: 0007_drawbridge_hnsw
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op

revision = "0008_codeguard_rls"
down_revision = "0007_drawbridge_hnsw"
branch_labels = None
depends_on = None


_TENANT_TABLES = ("compliance_checks", "permit_checklists")


def upgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
