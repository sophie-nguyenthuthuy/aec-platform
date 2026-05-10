"""retention_overrides — per-tenant TTL extensions for retention policies

Cycle O3 shipped the retention surface as read-only and explicitly
called out per-tenant overrides as out-of-scope. T3 closes the gap:
compliance-conscious customers can extend their `audit_events`
retention from the 365d default to 7y (or any other table's TTL)
without changing platform-wide defaults.

Schema rationale:

  * **Composite PK on `(organization_id, table_name)`.** At most
    one override per (tenant, table). The retention cron's per-table
    loop checks this row before falling back to env / policy default.

  * **`ttl_days` is the only mutable field.** No `archive` override
    in v1 — every customer's archive policy is platform-wide. Adding
    `archive_override` would be a follow-up if a single customer
    ever wants to opt out of S3 archives despite the global default.

  * **`set_by` / `set_at` for audit.** Compliance reviewers ask "who
    extended retention to 7y, and when?" — these columns plus an
    audit row at write time give the answer. Optional FK to users
    (SET NULL on delete) so a removed admin's overrides survive
    them.

  * **No retention on retention_overrides itself.** A row stays
    until manually cleared. The whole point is operator intent.

Revision ID: 0046_retention_overrides
Revises: 0045_cron_alert_dedup
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_retention_overrides"
down_revision = "0045_cron_alert_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retention_overrides",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Mirrors `services.retention.RetentionPolicy.table` —
        # validated by the service helper against the registry so a
        # row for a non-managed table never lands.
        sa.Column("table_name", sa.Text, nullable=False),
        # The override's TTL in days. Service helper validates ≥ the
        # policy's `default_days` (you can EXTEND retention for
        # compliance, not SHORTEN it — shortening would let an org
        # opt out of governance commitments).
        sa.Column("ttl_days", sa.Integer, nullable=False),
        sa.Column(
            "set_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Optional free-text reason. Compliance reviewers like
        # "ISO 27001 audit retention requirement" — surfaces in the
        # admin UI as a tooltip on each override row.
        sa.Column("reason", sa.Text),
        sa.PrimaryKeyConstraint(
            "organization_id", "table_name",
            name="pk_retention_overrides",
        ),
    )

    # Per-org listing — "show me my overrides." The cron's per-row
    # `policy_ttl_days(...)` lookup is a single-row PK fetch (no
    # index needed beyond the PK).
    op.create_index(
        "ix_retention_overrides_org",
        "retention_overrides",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_retention_overrides_org", table_name="retention_overrides")
    op.drop_table("retention_overrides")
