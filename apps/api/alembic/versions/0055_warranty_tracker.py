"""WarrantyTracker — claims workflow + reminder idempotency.

Builds on existing `warranty_items` (from handover module). Two new tables:

  * `warranty_claims` — when something breaks under warranty, the
    customer files a claim. Tracked through a status workflow:
    open → investigating → vendor_notified → in_repair → resolved
                                                       ↘ rejected
    Each claim has an audit trail of status changes + cost actuals
    (warranty SHOULD cover this but real VN B2B is messier).

  * `warranty_reminders_sent` — idempotency for the daily cron that
    emails the vendor + customer N days before expiry. Cron runs
    every morning + the dedupe key prevents same-window double-send.
    Composite UQ on (warranty_id, days_before_expiry, sent_date)
    means we send at most once per (warranty, window, day).

Why a separate table for reminders instead of a flag on warranty_items:
  * Cron logic is N days before expiry. Multiple windows per warranty
    (60-day, 30-day, 7-day) → not a single flag.
  * Idempotency on cron restarts — if the worker crashes mid-fan-out
    + restarts, we don't re-email warranties already notified.
  * Auditable history: "did we ACTUALLY send the 30-day notice?
    what date? who recorded it?"

Revision ID: 0055_warranty_tracker
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_warranty_tracker"
down_revision: Union[str, None] = "0054_subcontractor_portal"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ---------- warranty_claims ----------
    op.create_table(
        "warranty_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warranty_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warranty_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # open | investigating | vendor_notified | in_repair |
        # resolved | rejected | abandoned
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        # Severity drives prioritisation. minor (cosmetic), major
        # (degrades function), critical (safety / blocks occupancy).
        sa.Column("severity", sa.Text, nullable=False, server_default="major"),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # Reporter — usually the building owner / facilities manager.
        sa.Column("reporter_name", sa.Text, nullable=True),
        sa.Column("reporter_email", sa.Text, nullable=True),
        sa.Column("reporter_phone", sa.Text, nullable=True),
        # Tracking dates
        sa.Column("reported_on", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("acknowledged_on", sa.Date, nullable=True),
        sa.Column("resolved_on", sa.Date, nullable=True),
        # Cost: who-paid is critical for VN warranty disputes.
        # vendor_covered = warranty paid; contractor_absorbed = we ate it.
        sa.Column("cost_vnd", sa.BigInteger, nullable=True),
        sa.Column("paid_by", sa.Text, nullable=True),
        # Optional FK to a defect (if the claim originated from
        # punch-list / inspection finding).
        sa.Column(
            "linked_defect_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("defects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Photos / contract docs / invoices
        sa.Column(
            "evidence_file_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'vendor_notified', "
            "'in_repair', 'resolved', 'rejected', 'abandoned')",
            name="ck_warranty_claims_status",
        ),
        sa.CheckConstraint(
            "severity IN ('minor', 'major', 'critical')",
            name="ck_warranty_claims_severity",
        ),
        sa.CheckConstraint(
            "paid_by IS NULL OR paid_by IN ('vendor_covered', 'contractor_absorbed', 'owner_paid', 'shared')",
            name="ck_warranty_claims_paid_by",
        ),
        sa.CheckConstraint(
            "cost_vnd IS NULL OR cost_vnd >= 0",
            name="ck_warranty_claims_cost_nonneg",
        ),
    )
    op.create_index(
        "ix_warranty_claims_org_status",
        "warranty_claims",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_warranty_claims_warranty_item",
        "warranty_claims",
        ["warranty_item_id"],
    )

    # ---------- warranty_reminders_sent ----------
    op.create_table(
        "warranty_reminders_sent",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warranty_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warranty_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Which window did we notify about? 60, 30, 7, 0 (day-of).
        sa.Column("days_before_expiry", sa.Integer, nullable=False),
        # When the cron actually sent the email — used to detect drift
        # (cron should run daily; if last_sent is >2 days old we know
        # the cron is broken).
        sa.Column("sent_date", sa.Date, nullable=False),
        # Email recipients (comma-separated to keep schema flat;
        # multi-row design would be overkill for an audit table).
        sa.Column("recipients", sa.Text, nullable=False),
        # Mailer delivery state — needed for re-sending if Resend
        # failed (delivered=False on a 4xx).
        sa.Column("delivered", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Composite UQ: at most one row per (warranty, window) — cron
        # is idempotent. If a retry-by-hand needs to send again,
        # operator deletes the row OR uses a different window value.
        sa.UniqueConstraint(
            "warranty_item_id",
            "days_before_expiry",
            name="uq_warranty_reminder_per_window",
        ),
    )
    op.create_index(
        "ix_warranty_reminders_org_sent",
        "warranty_reminders_sent",
        ["organization_id", "sent_date"],
    )

    # ---------- RLS ----------
    for table in ("warranty_claims", "warranty_reminders_sent"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table}
              ON {table}
              USING (organization_id = current_setting('app.current_org_id', true)::uuid)
              WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("warranty_reminders_sent")
    op.drop_table("warranty_claims")
