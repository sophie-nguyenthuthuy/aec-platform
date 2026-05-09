"""slack_deliveries: per-attempt log of `services.slack.send_slack` outcomes

Pairs with `send_slack(..., kind=...)` opt-in persistence. Without
this table, ops only learns "Slack didn't fire" by reading worker
logs — and "didn't fire" is invisible until someone goes looking.
The mailer counterpart relies on each caller's own table for the
same purpose; Slack lacks a natural caller-side log because
`ops_alerts` is the primary caller and is itself stateless.

Schema choices:

  * `kind` is a free-form string (e.g. `"scraper_drift"`,
    `"rfq_deadline_summary"`) chosen by the caller. Free-form
    instead of an enum because adding a new kind is a one-line
    code change and we don't want a migration churn for it.

  * `delivered`, `reason`, `status_code` mirror the
    `send_slack(...)` return shape exactly so the persistence is a
    1:1 dump rather than a re-derivation. Reason is null on
    success; status_code is the HTTP status returned by Slack
    (null on transport failures + the not-configured no-op).

  * `text_preview` caps the original message at 200 chars. We
    intentionally don't store the full text + blocks — Slack
    payloads can be kilobytes once a daily digest goes out, and the
    failure-debugging value drops off after the first sentence.

  * `(kind, created_at DESC)` index covers the dominant query —
    "recent failures for kind X" in an admin dashboard.

  * No `organization_id`. Slack alerts are platform-level (one
    webhook URL serves every tenant in the cron path), so the
    tenant column would always be null.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_slack_deliveries"
down_revision = "0036_scraper_rule_hits_by_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_deliveries",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("text_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_slack_deliveries_kind_created_at",
        "slack_deliveries",
        ["kind", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_slack_deliveries_kind_created_at", table_name="slack_deliveries")
    op.drop_table("slack_deliveries")
