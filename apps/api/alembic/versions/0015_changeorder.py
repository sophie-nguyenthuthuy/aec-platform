"""changeorder extension tables

The base `change_orders` table already exists (from 0002_pulse). This
migration adds the supporting tables for sources, line items, approvals,
and AI candidates.

Revision ID: 0015_changeorder
Revises: 0014_project_watches
Create Date: 2026-04-26
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0015_changeorder"
down_revision = "0014_project_watches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_order_sources",
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
            "change_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("change_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "rfi_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfis.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_log_observations.id", ondelete="SET NULL"),
        ),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_change_order_sources_co",
        "change_order_sources",
        ["change_order_id"],
    )

    op.create_table(
        "change_order_line_items",
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
            "change_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("change_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("line_kind", sa.Text(), nullable=False, server_default="add"),
        sa.Column("spec_section", sa.Text()),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit", sa.Text()),
        sa.Column("unit_cost_vnd", sa.BigInteger()),
        sa.Column("cost_vnd", sa.BigInteger()),
        sa.Column("schedule_impact_days", sa.Integer()),
        sa.Column(
            "schedule_activity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_activities.id", ondelete="SET NULL"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_change_order_line_items_co",
        "change_order_line_items",
        ["change_order_id", "sort_order"],
    )

    op.create_table(
        "change_order_approvals",
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
            "change_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("change_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text()),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_change_order_approvals_co",
        "change_order_approvals",
        ["change_order_id", "created_at"],
    )

    op.create_table(
        "change_order_candidates",
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
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "source_rfi_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfis.id", ondelete="SET NULL"),
        ),
        sa.Column("source_text_snippet", sa.Text()),
        sa.Column("proposal", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column(
            "accepted_co_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("change_orders.id", ondelete="SET NULL"),
        ),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("rejected_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("rejected_reason", sa.Text()),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_change_order_candidates_project",
        "change_order_candidates",
        ["project_id", "created_at"],
    )

    for table in (
        "change_order_sources",
        "change_order_line_items",
        "change_order_approvals",
        "change_order_candidates",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in (
        "change_order_candidates",
        "change_order_approvals",
        "change_order_line_items",
        "change_order_sources",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
