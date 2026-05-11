"""audit_pins — admin bookmarks on audit_events for incident retros

Cycle U3: when admins review an incident they often want to flag
"this row is the smoking gun" so subsequent navigation across the
paginated audit page doesn't lose it. Pinned rows always render at
top of `/settings/audit` regardless of filter / page state, with a
small note field for the reviewer's annotation.

Schema rationale:

  * **Composite PK on `(audit_event_id, pinned_by)`.** Each user
    can pin a row once. A row can be pinned by multiple admins
    (different reviewers, different annotations) — the listing UI
    deduplicates by audit_event_id and shows whichever pin the
    current user owns.
  * **`note` is optional.** Quick "smoking gun" flags don't need
    an annotation; compliance reviews benefit from the trail.
    500-char cap matches the audit reason field idiom.
  * **No own-table retention.** Pins persist until manually cleared
    OR until the underlying `audit_event` ages out (the FK CASCADE
    drops orphan pin rows when the audit row goes).

Revision ID: 0047_audit_pins
Revises: 0046_retention_overrides
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047_audit_pins"
down_revision = "0046_retention_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_pins",
        sa.Column(
            "audit_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audit_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pinned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("note", sa.Text),
        sa.PrimaryKeyConstraint("audit_event_id", "pinned_by", name="pk_audit_pins"),
    )

    # Per-user listing index — drives "show me my pinned rows" on
    # /settings/audit.
    op.create_index(
        "ix_audit_pins_pinned_by",
        "audit_pins",
        ["pinned_by", sa.text("pinned_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_pins_pinned_by", table_name="audit_pins")
    op.drop_table("audit_pins")
