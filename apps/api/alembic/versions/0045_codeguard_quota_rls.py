"""enable RLS on codeguard quota audit / notification / usage-by-route tables

Discovered by `tests/test_rls_coverage.py::test_every_org_scoped_table_has_rls_enabled`
during the May 2026 test pass. Three tables added between migrations 0026
and 0040 carry an `organization_id` but were never wrapped in the
`tenant_isolation_*` policy convention every sibling module uses:

  * `codeguard_quota_audit_log`                — 0026
  * `codeguard_quota_threshold_notifications`  — 0030
  * `codeguard_user_usage_by_route`            — 0040

Each one stores per-tenant audit / notification / usage telemetry. The
codeguard service layer always filters reads by `organization_id`, so no
prod data has leaked — but the defense-in-depth pattern (a `current_setting
('app.current_org_id')` policy at the DB level) is the same one applied to
`compliance_checks` / `permit_checklists` in 0008. Bringing these three in
line so a routing bug can never cross-tenant leak.

Revision ID: 0045_codeguard_quota_rls
Revises: 0044_thanhtoan
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op

revision = "0045_codeguard_quota_rls"
down_revision = "0044_thanhtoan"
branch_labels = None
depends_on = None


_TENANT_TABLES = (
    "codeguard_quota_audit_log",
    "codeguard_quota_threshold_notifications",
    "codeguard_user_usage_by_route",
)


def upgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # Match the policy name convention from 0008_codeguard_rls so
        # `pg_policy` greps stay consistent across the codeguard surface.
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
