"""winwork module tables

Revision ID: 0002_winwork
Revises: 0001_core
Create Date: 2026-04-22
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_winwork"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="draft"),
        sa.Column("client_name", sa.Text),
        sa.Column("client_email", sa.Text),
        sa.Column("scope_of_work", postgresql.JSONB),
        sa.Column("fee_breakdown", postgresql.JSONB),
        sa.Column("total_fee_vnd", sa.BigInteger),
        sa.Column("total_fee_currency", sa.Text, server_default="VND"),
        sa.Column("valid_until", sa.Date),
        sa.Column("ai_generated", sa.Boolean, server_default=sa.false()),
        sa.Column("ai_confidence", sa.Numeric),
        sa.Column("notes", sa.Text),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("responded_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_proposals_org_status", "proposals", ["organization_id", "status"])
    op.create_index("ix_proposals_org_created", "proposals", ["organization_id", sa.text("created_at DESC")])

    op.create_table(
        "proposal_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("discipline", sa.Text),
        sa.Column("project_types", postgresql.ARRAY(sa.Text)),
        sa.Column("content", postgresql.JSONB),
        sa.Column("is_default", sa.Boolean, server_default=sa.false()),
    )
    op.create_index("ix_proposal_templates_org", "proposal_templates", ["organization_id"])

    op.create_table(
        "fee_benchmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("discipline", sa.Text, nullable=False),
        sa.Column("project_type", sa.Text, nullable=False),
        sa.Column("country_code", sa.CHAR(2), nullable=False),
        sa.Column("province", sa.Text),
        sa.Column("area_sqm_min", sa.Numeric),
        sa.Column("area_sqm_max", sa.Numeric),
        sa.Column("fee_percent_low", sa.Numeric),
        sa.Column("fee_percent_mid", sa.Numeric),
        sa.Column("fee_percent_high", sa.Numeric),
        sa.Column("source", sa.Text),
        sa.Column("valid_from", sa.Date),
        sa.Column("valid_to", sa.Date),
    )
    op.create_index(
        "ix_fee_benchmarks_lookup",
        "fee_benchmarks",
        ["country_code", "discipline", "project_type"],
    )

    # RLS on tenant-owned tables
    for table in ("proposals", "proposal_templates"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    op.drop_table("fee_benchmarks")
    op.drop_table("proposal_templates")
    op.drop_table("proposals")
