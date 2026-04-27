"""punch list tables (owner walkthroughs)

Tables:
  * punch_lists
  * punch_items

RLS: tenant-scoped via app.current_org_id, same pattern as the other modules.

Revision ID: 0020_punchlist
Revises: 0019_activity_feed_indexes
Create Date: 2026-04-27
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0020_punchlist"
down_revision = "0019_activity_feed_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "punch_lists",
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
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("walkthrough_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("owner_attendees", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("signed_off_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "signed_off_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_punch_lists_project_date",
        "punch_lists",
        ["project_id", "walkthrough_date"],
    )
    op.create_index("ix_punch_lists_status", "punch_lists", ["organization_id", "status"])

    op.create_table(
        "punch_items",
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
            "list_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("punch_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column("trade", sa.Text(), nullable=False, server_default="architectural"),
        sa.Column("severity", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column(
            "photo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("due_date", sa.Date()),
        sa.Column("fixed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("list_id", "item_number", name="uq_punch_items_list_number"),
    )
    op.create_index(
        "ix_punch_items_list", "punch_items", ["list_id", "item_number"]
    )
    op.create_index(
        "ix_punch_items_status", "punch_items", ["organization_id", "status"]
    )
    op.create_index(
        "ix_punch_items_assigned",
        "punch_items",
        ["assigned_user_id"],
        postgresql_where=sa.text("assigned_user_id IS NOT NULL"),
    )

    for table in ("punch_lists", "punch_items"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("punch_items", "punch_lists"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
