"""codeguard: dedupe table for 80%/95% quota threshold emails

When an org's monthly usage crosses 80% (warn) or 95% (critical) on
either dimension, we want to email the org's `quota_warn` opt-in list
exactly once per `(org, dimension, threshold, period)`. Without a
dedupe table, every successful `record_org_usage` call past the
threshold would re-trigger the email — flapping inboxes and getting
the alerts ignored within hours.

Schema choices:

  * Composite PK on `(organization_id, dimension, threshold, period_start)`.
    The whole row IS the dedupe key — there's no surrogate id because
    nothing references this table by id. Smaller index, faster
    INSERT…ON CONFLICT path.

  * `dimension` is text rather than an enum so a future "embed_tokens"
    or "scan_minutes" dimension doesn't need a migration. Same
    reasoning that kept `codeguard_quota_audit_log.action` as text.

  * `threshold` stored as the integer percent (80, 95) not a float —
    we don't ever want a float-comparison surprise turning "95.0" into
    "94.9999..." and re-firing the email.

  * No FK on `period_start` — `codeguard_org_usage.period_start` isn't
    a unique key on its own (composite with org), and bringing in a
    composite FK would force every period rollover to play games with
    cascade rules. The (org_id, period_start) tuple is implicitly
    consistent because the same SQL that writes here reads from
    codeguard_org_usage.

  * `organization_id` FK to `organizations.id` ON DELETE CASCADE — if
    the org is deleted, the dedupe rows go with it. Different choice
    from `codeguard_quota_audit_log` (SET NULL there) because dedupe
    rows are purely operational state, not a paper trail.

Revision ID: 0030_codeguard_quota_thresholds
Revises: 0029_import_jobs
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Kept under 32 chars — `alembic_version.version_num` is VARCHAR(32),
# longer revision IDs hard-fail the version table update.
revision = "0030_codeguard_quota_thresholds"
down_revision = "0029_import_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codeguard_quota_threshold_notifications",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # `input` | `output` (today). Free-text rather than enum — same
        # forward-compat reasoning as the audit log's `action` column.
        sa.Column("dimension", sa.Text(), nullable=False),
        # 80 or 95 (today). Integer not float to avoid edge cases where
        # 94.9999% rounds and silently re-fires the email.
        sa.Column("threshold", sa.Integer(), nullable=False),
        # First-of-month date. Same shape as `codeguard_org_usage.period_start`.
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column(
            "sent_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # Composite PK = the dedupe key. The whole row's identity.
        sa.PrimaryKeyConstraint(
            "organization_id",
            "dimension",
            "threshold",
            "period_start",
            name="pk_codeguard_quota_threshold_notifications",
        ),
    )


def downgrade() -> None:
    op.drop_table("codeguard_quota_threshold_notifications")
