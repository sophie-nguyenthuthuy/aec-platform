"""project_watches: per-user opt-in for daily activity digests

A user "watches" a project to opt in to the daily digest email — only
watched projects feed into the morning roll-up. The activity-feed *page*
remains org-wide; watches are about *push*, not visibility.

Schema rationale:
  * `(user_id, project_id)` UNIQUE so a user can't double-watch the same
    project (the API can do an idempotent INSERT ON CONFLICT DO NOTHING).
  * `organization_id` is denormalized from `projects.organization_id` so
    the standard RLS policy `organization_id = current_setting('app.current_org_id')::uuid`
    applies without joining. Worth the redundancy — every read is
    tenant-scoped, joins would inflate query plans.
  * Index `(user_id, organization_id)` — the digest cron's hot path is
    "give me all watches for user U in org O".

Revision ID: 0014_project_watches
Revises: 0013_merge_post_schedulepilot, 0013_dailylog
Create Date: 2026-04-26

Note: this revision doubles as the merge point for the two parallel
0013 heads (`0013_merge_post_schedulepilot` from the post-schedulepilot
fan-in, and `0013_dailylog` which landed concurrently from the dailylog
module). Carrying real DDL on a merge revision is supported by Alembic
— the merge semantics come from the `down_revision` tuple, the upgrade
itself runs the table-creation as normal.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0014_project_watches"
down_revision = ("0013_merge_post_schedulepilot", "0013_dailylog")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_watches",
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
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_watches_user_project"),
    )
    op.create_index(
        "ix_project_watches_user_org",
        "project_watches",
        ["user_id", "organization_id"],
    )

    # RLS — same shape as every other tenant-scoped table on the platform.
    op.execute("ALTER TABLE project_watches ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_project_watches
            ON project_watches
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_project_watches ON project_watches")
    op.drop_index("ix_project_watches_user_org", table_name="project_watches")
    op.drop_table("project_watches")
