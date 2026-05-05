"""notification_preferences — per-user opt-in for ops/digest alerts

Per-user/per-org switches for things like drift-alert emails and
RFQ-deadline digests. Today drift alerts blast to `OPS_ALERT_EMAILS`
(env var) — fine for a tiny ops team but doesn't scale as users grow.
This table lets each admin opt into specific alert kinds; senders fall
back to `OPS_ALERT_EMAILS` only when no users have the relevant pref
enabled (so existing deploys keep working).

Schema:

  * `(user_id, organization_id, key)` is unique — a user gets one row
    per alert kind, per org.
  * `key` is a stable string discriminator: `scraper_drift`,
    `rfq_deadline_summary`, `weekly_digest_email`, etc. Strings rather
    than an enum so adding a new alert kind doesn't need a migration.
  * `email_enabled` and `slack_enabled` are separate booleans —
    callers can opt into one channel without the other once Slack
    delivery exists. Both default to `false` so creating a row
    requires explicit consent.
  * RLS scoped on `organization_id` + tighter check via auth: the
    `notifications` router only lets a user mutate their *own* prefs
    in the *current* org.

Revision ID: 0025_notification_prefs
Revises: 0024_rfq_acceptance
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0025_notification_prefs"
down_revision = "0024_rfq_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("email_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("slack_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "organization_id", "key", name="uq_notif_prefs_user_org_key"
        ),
    )

    # Tenant-isolation RLS. Even though the FK + auth already gate
    # writes, RLS is the consistent platform posture (see
    # tests/test_rls_coverage.py). Without it, a hypothetical bug that
    # used `SessionFactory` for a cross-tenant scan would silently leak.
    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_notification_preferences "
        "ON notification_preferences "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_notification_preferences ON notification_preferences")
    op.execute("ALTER TABLE notification_preferences DISABLE ROW LEVEL SECURITY")
    op.drop_table("notification_preferences")
