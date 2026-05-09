"""cron_alerts_sent — dedup ratchet for the cron failure watchdog

A cron failing 5 minutes in a row currently produces 5 separate
Slack messages — every watchdog tick re-discovers the failure and
re-alerts. Operators tune out the noise; a genuine new failure
gets buried.

This table tracks the LAST alert per (cron_name, kind) so the
watchdog can suppress duplicate messages for the same ongoing
failure. Re-alerts at deliberate intervals (30min, 6h) carry the
"still failing for X" framing — same shape as PagerDuty's repeat
frequency.

Schema rationale:

  * **Composite PK on (cron_name, kind).** Each cron has at most
    one outstanding alert per kind (`cron_failure` or `cron_stuck`).
    The watchdog UPSERTs into this table; ON CONFLICT updates
    `last_alert_at` + bumps `alert_count`.

  * **`alert_count` is the repeat counter.** Starts at 1; bumps
    on every re-alert. The Slack message renders "(3rd alert)" so
    operators see the failure has been ongoing without clicking
    through to the dashboard.

  * **`first_alert_at` stays put.** Once set, never updated. The
    watchdog renders "failing for 47m" using
    `NOW() - first_alert_at` so a re-alert carries the cumulative
    duration, not just the time since last alert.

  * **No `organization_id`.** Crons are platform-wide — same
    rationale as `cron_runs`. The audit_events table carries per-
    tenant attribution where it matters.

  * **Pruned by retention.** Default 7 days — long enough that a
    cron failing intermittently keeps the dedup state across
    flaky weeks, short enough that resolved alerts don't bloat
    the table forever.

Revision ID: 0045_cron_alert_dedup
Revises: 0043_webhook_secret_rotation
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_cron_alert_dedup"
down_revision = "0043_webhook_secret_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cron_alerts_sent",
        # Composite PK: at most one row per (cron_name, kind). The
        # watchdog UPSERTs; ON CONFLICT updates the existing row.
        sa.Column("cron_name", sa.Text, nullable=False),
        # 'cron_failure' | 'cron_stuck'. Mirrors the kind values in
        # services.cron_alerts._KIND constants.
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column(
            "first_alert_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_alert_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Repeat counter. Starts at 1 on first alert; bumps on each
        # re-alert. Slack message uses this to render "(3rd alert)".
        sa.Column(
            "alert_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.PrimaryKeyConstraint("cron_name", "kind", name="pk_cron_alerts_sent"),
    )

    # Index for the cleanup sweep — "find rows older than N days."
    # The retention prune walks this index instead of doing a seq
    # scan on the whole table.
    op.create_index(
        "ix_cron_alerts_sent_last_alert_at",
        "cron_alerts_sent",
        ["last_alert_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cron_alerts_sent_last_alert_at", table_name="cron_alerts_sent")
    op.drop_table("cron_alerts_sent")
