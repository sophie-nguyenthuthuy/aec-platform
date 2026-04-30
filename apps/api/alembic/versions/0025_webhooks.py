"""webhooks: per-org HTTP callbacks for cross-system integration

Two tables, one workflow:

  * `webhook_subscriptions` — admin-issued config row. One per
    (organization, url) pair (unique constraint on that pair so a
    customer can't accidentally double-subscribe). `event_types` is
    a text[] of dotted slugs the subscriber wants delivered (matches
    `services/audit.AuditAction` shape: `pulse.change_order.approve`,
    `siteeye.safety_incident.detected`, etc.). `secret` is a 32-byte
    random token used to HMAC-sign every payload — receivers verify
    via `hmac.compare_digest(local_hmac(body), header)`.

  * `webhook_deliveries` — outbox table. One row per (subscription,
    event) pair. Status transitions: pending → in_flight → delivered |
    failed. `attempt_count` + `next_retry_at` drive exponential-
    backoff retry from the arq cron (1m → 5m → 30m → 2h → 12h, then
    permanent fail). `failed` rows stay around for forensics; an ops
    runbook can re-queue them with a one-line UPDATE.

The split mirrors a classic outbox pattern: inserting into
`webhook_deliveries` happens in the *same transaction* as the source
event, so a rollback elsewhere drops the delivery row too — we never
notify a customer about a write that didn't actually commit.

Revision ID: 0025_webhooks
Revises: 0024_rfq_acceptance
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0025_webhooks"
down_revision = "0024_rfq_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        # 32-byte random; rendered as hex (64 chars). Stored in plain
        # text — there's no value in encrypting since we need the raw
        # secret to sign payloads, and the row itself is RLS-protected.
        sa.Column("secret", sa.Text, nullable=False),
        # Empty array = subscribe to ALL events. Otherwise the dispatcher
        # only fires when `event_type = ANY(event_types)`.
        sa.Column(
            "event_types",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_delivery_at", sa.TIMESTAMP(timezone=True)),
        # Rolling counter — incremented on every failed delivery,
        # zeroed on a successful one. Crosses a threshold (default 20)
        # → the dispatcher auto-disables the subscription so we don't
        # hammer a dead endpoint forever.
        sa.Column(
            "failure_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id", "url", name="uq_webhook_subs_org_url"
        ),
    )
    op.create_index(
        "ix_webhook_subs_org_enabled",
        "webhook_subscriptions",
        ["organization_id", "enabled"],
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Carry org_id explicitly so the cron's discovery query (which
        # bypasses RLS via AdminSessionFactory) can still report on
        # per-tenant delivery health.
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_body_snippet", sa.Text),  # first 500 chars; ops debug aid
        sa.Column("error_message", sa.Text),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_flight', 'delivered', 'failed')",
            name="ck_webhook_deliveries_status",
        ),
    )
    # The cron's hot path: "give me pending deliveries whose retry
    # window has elapsed". Index covers the WHERE + ORDER BY in one shot.
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["status", "next_retry_at"],
        postgresql_where=sa.text("status IN ('pending', 'in_flight')"),
    )
    # Drill-down: "show me the recent deliveries for this subscription".
    op.create_index(
        "ix_webhook_deliveries_sub_created",
        "webhook_deliveries",
        ["subscription_id", sa.text("created_at DESC")],
    )

    # RLS — same shape as every other tenant-scoped table.
    for table in ("webhook_subscriptions", "webhook_deliveries"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
                USING (organization_id = current_setting('app.current_org_id', true)::uuid)
                WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in ("webhook_deliveries", "webhook_subscriptions"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
    op.drop_index("ix_webhook_deliveries_sub_created", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_due", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_subs_org_enabled", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")
