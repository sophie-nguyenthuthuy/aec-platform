"""greenmark tables — VGBC LOTUS + IFC EDGE scoring

Tables:
  * green_certifications  — certification pursuit (per project, system)
  * green_credits         — line-item credits / measures

Revision ID: 0047_greenmark
Revises: 0046_einvoice
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0047_greenmark"
down_revision = "0046_einvoice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "green_certifications",
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
        sa.Column("system", sa.Text(), nullable=False),
        sa.Column("target_level", sa.Text(), nullable=False),
        sa.Column("achieved_level", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="planning"),
        sa.Column("achieved_points", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("max_points", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column(
            "project_brief",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("certification_no", sa.Text()),
        sa.Column("awarded_at", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.Column("assessor_name", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "system", name="uq_green_certifications_project_system"),
        sa.CheckConstraint(
            "system IN ('lotus_nr', 'lotus_homes', 'lotus_bio', 'lotus_intl', 'edge')",
            name="ck_green_certifications_system",
        ),
        sa.CheckConstraint(
            "target_level IN ('certified', 'silver', 'gold', 'platinum', "
            "'edge_certified', 'edge_advanced', 'edge_zero')",
            name="ck_green_certifications_target_level",
        ),
        sa.CheckConstraint(
            "status IN ('planning', 'self_assessment', 'submitted', 'provisional', "
            "'final_cert', 'rejected', 'expired')",
            name="ck_green_certifications_status",
        ),
    )
    op.create_index("ix_green_certifications_project", "green_certifications", ["organization_id", "project_id"])
    op.create_index("ix_green_certifications_status", "green_certifications", ["organization_id", "status"])

    op.create_table(
        "green_credits",
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
            "certification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("green_certifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="not_attempted"),
        sa.Column("max_points", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("claimed_points", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("awarded_points", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column(
            "computed_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence_file_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("reviewer_note", sa.Text()),
        sa.Column(
            "reviewer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("certification_id", "code", name="uq_green_credits_cert_code"),
        sa.CheckConstraint(
            "category IN ('energy', 'water', 'materials', 'ieq', 'site', 'operations', 'innovation')",
            name="ck_green_credits_category",
        ),
        sa.CheckConstraint(
            "status IN ('not_attempted', 'targeted', 'documented', 'verified', 'rejected')",
            name="ck_green_credits_status",
        ),
        sa.CheckConstraint(
            "max_points >= 0 AND claimed_points >= 0 AND awarded_points >= 0",
            name="ck_green_credits_points_nonneg",
        ),
    )
    op.create_index("ix_green_credits_cert", "green_credits", ["certification_id", "category"])

    for table in ("green_certifications", "green_credits"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("green_credits", "green_certifications"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
