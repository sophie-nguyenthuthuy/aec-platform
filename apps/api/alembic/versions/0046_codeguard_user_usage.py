"""create the missing codeguard_user_usage table (per-user attribution sidecar)

The `record_user_usage` service in `services/codeguard_quota_attribution.py`
writes per-user token totals to a table named `codeguard_user_usage`, but
no migration ever created that table — only the per-route variant
(`codeguard_user_usage_by_route` from migration 0040) ships in the chain.

Discovered May 2026 while running the integration test lane: the
`test_cmd_usage_by_route_*` tests INSERT seed rows into both tables and
fail at the parent insert with `UndefinedTableError: relation
"codeguard_user_usage" does not exist`. In production the missing-table
error is swallowed by the surrounding `try/except Exception:` in
`record_user_usage`'s call site (line 252-271 of the service file), so
the user-attribution column on the admin "top users this month" dashboard
silently shows zeros instead of breaking the request — but every LLM call
also logs a WARNING which has been filling the logs without anyone
catching the root cause.

Shape mirrors `codeguard_user_usage_by_route` minus the `route_key`
column, with the same composite PK pattern `(organization_id, user_id,
period_start)`. BIGINT for token counts so weighted writes (`route_weight`
up to 5×) don't overflow. RLS enabled to match the convention enforced by
`test_every_org_scoped_table_has_rls_enabled`.

Revision ID: 0046_codeguard_user_usage
Revises: 0045_codeguard_quota_rls
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_codeguard_user_usage"
down_revision = "0045_codeguard_quota_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codeguard_user_usage",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column(
            "input_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "output_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # Composite PK is the UPSERT target. One row per
        # (org, user, month) — the per-route breakdown lives in
        # codeguard_user_usage_by_route.
        sa.PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            "period_start",
            name="pk_codeguard_user_usage",
        ),
    )

    # Index supporting the "top users this month" dashboard query —
    # sorted by combined tokens DESC so a LIMIT-N scan serves directly.
    op.create_index(
        "ix_codeguard_user_usage_org_period_total_desc",
        "codeguard_user_usage",
        [
            "organization_id",
            "period_start",
            sa.text("(input_tokens + output_tokens) DESC"),
        ],
    )

    # RLS — same `tenant_isolation_*` pattern as
    # 0008_codeguard_rls / 0043_codeguard_quota_rls.
    op.execute("ALTER TABLE codeguard_user_usage ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_codeguard_user_usage "
        "ON codeguard_user_usage "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
        "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_codeguard_user_usage "
        "ON codeguard_user_usage"
    )
    op.execute("ALTER TABLE codeguard_user_usage DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_codeguard_user_usage_org_period_total_desc",
        table_name="codeguard_user_usage",
    )
    op.drop_table("codeguard_user_usage")
