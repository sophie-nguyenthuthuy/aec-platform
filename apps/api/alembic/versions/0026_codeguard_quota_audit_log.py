"""codeguard: quota audit log for CLI mutations

Adds `codeguard_quota_audit_log` so every `set` / `reset` operation on
the quota or usage tables leaves a paper trail. Without this, ops can't
answer "who raised this org's cap last week" without grepping shell
history — the audit table makes that question a single SELECT.

Schema choices worth noting:

  * `before` / `after` are JSONB rather than typed columns. The CLI
    writes both `quota` mutations (limit columns) and `usage` mutations
    (`reset` zeros the running totals); their column shapes differ.
    Storing structured snapshots keeps the table generic without
    needing per-action subclasses.

  * `actor` is a free-text string (the OS username by default, or
    whatever the operator passes via `--actor`). It's NOT a FK to
    `users` — many ops engineers wouldn't have rows there, and
    requiring it would make the audit log refuse to record exactly
    the events compliance cares about.

  * `organization_id` is a FK to `organizations.id` ON DELETE SET NULL.
    Cascading deletion of audit rows on org delete would lose the
    paper trail at exactly the moment it's most needed. SET NULL
    preserves the rest of the row.

  * No RLS. Audit reads are restricted at the application layer —
    only platform admins should query this; rolling RLS in would block
    the CLI itself unless we pass `app.current_org_id` for every
    operation, which the CLI doesn't have.

Revision ID: 0026_codeguard_quota_audit_log
Revises: ceff072b3343
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0026_codeguard_quota_audit_log"
down_revision = "ceff072b3343"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codeguard_quota_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # `quota_set`, `quota_reset`. Free-text rather than enum so a
        # future action (`quota_unset`, etc.) doesn't require a migration.
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        # OS username from `os.getenv('USER')` by default. CLI accepts
        # `--actor` for operators running under a service account.
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    # The dominant query pattern is "audit history for one org, most
    # recent first" — index `(organization_id, occurred_at DESC)` so
    # that's a single index seek, not a full table scan.
    op.create_index(
        "ix_codeguard_quota_audit_log_org_time",
        "codeguard_quota_audit_log",
        ["organization_id", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_codeguard_quota_audit_log_org_time", table_name="codeguard_quota_audit_log")
    op.drop_table("codeguard_quota_audit_log")
