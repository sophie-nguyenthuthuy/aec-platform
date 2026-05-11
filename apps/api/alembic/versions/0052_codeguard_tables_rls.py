"""enable RLS on the four codeguard quota tables

Revision ID: 0052_codeguard_tables_rls
Revises: 0051_retention_rls_with_check
Create Date: 2026-05-10

Closes a real gap caught by `tests/test_rls_coverage.py::
test_every_org_scoped_table_has_rls_enabled`. The four codeguard
quota tables landed in migrations 0026 / 0029 / 0030 / 0040 with
an `organization_id` column but **no `ENABLE ROW LEVEL SECURITY`
+ tenant policy**. That meant a misconfigured caller (a service
that forgot to set `app.current_org_id`) could read or upsert
quota rows across orgs — the exact failure mode RLS exists to
prevent.

The fix here mirrors what every other org-scoped table in this
schema does — direct-`organization_id` USING + WITH CHECK clause
keyed off the session GUC. Same shape as the policies created by
0049_org_id_on_child_tables.

Tables affected (all tenant-scoped quota telemetry):
  * codeguard_user_usage          — per-user monthly token spend
  * codeguard_user_usage_by_route — per-user per-route breakdown
  * codeguard_quota_audit_log     — the org-level audit trail
  * codeguard_quota_threshold_notifications — Slack/email alert
                                              dedup state

Idempotent against any pre-existing policy of the same name
(none exist on these tables today, but the IF EXISTS / drop-then-
create pattern matches what 0049 settled on after we hit the
`tenant_isolation_boq_items` collision in CI).
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0052_codeguard_tables_rls"
down_revision = "0051_retention_rls_with_check"
branch_labels = None
depends_on = None


# Each entry: the table name. The policy name is derived as
# `tenant_isolation_<table>` to match the convention already
# established by 0002_costpulse, 0023_codeguard_quotas, and
# 0049_org_id_on_child_tables.
_TABLES = (
    "codeguard_user_usage",
    "codeguard_user_usage_by_route",
    "codeguard_quota_audit_log",
    "codeguard_quota_threshold_notifications",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # Drop-then-create so the migration is re-runnable on a
        # fresh DB even if the policy somehow lingered (it doesn't
        # today; this is defensive against re-targeted local DBs).
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    # Reverse order. DISABLE ROW LEVEL SECURITY drops the gate but
    # leaves the policy attached; we drop the policy too so a
    # subsequent re-upgrade gets a clean DROP-then-CREATE.
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
