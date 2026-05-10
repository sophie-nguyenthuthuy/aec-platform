"""retention_overrides — add WITH CHECK clause to the RLS policy

Migration 0048 created `tenant_isolation_retention_overrides` with
`USING` only. The 0021_rls_with_check_everywhere sweep had
established that every `tenant_isolation_*` policy gets BOTH `USING`
AND `WITH CHECK` — the gap allows an authenticated user to INSERT a
row with someone else's `organization_id` (the row becomes invisible
to them via USING, but it lands in the target tenant). 0048 was
written from the runbook's simpler example pattern and didn't carry
the WITH CHECK clause forward.

Fix is the same shape as 0021 for this single table: drop the
existing policy and recreate it with both clauses. A separate
follow-up migration (rather than editing 0048 in place) so already-
deployed environments pick the change up on the next upgrade.

Revision ID: 0051_retention_overrides_rls_with_check
Revises: 0050_index_org_id_on_child_tables
Create Date: 2026-05-10
"""

from __future__ import annotations

from alembic import op


revision = "0051_retention_overrides_rls_with_check"
down_revision = "0050_index_org_id_on_child_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_retention_overrides "
        "ON retention_overrides"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_retention_overrides ON retention_overrides "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
        "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_retention_overrides "
        "ON retention_overrides"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_retention_overrides ON retention_overrides "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )
