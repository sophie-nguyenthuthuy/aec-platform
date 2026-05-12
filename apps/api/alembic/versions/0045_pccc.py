"""pccc tables — fire-safety certification (QCVN 06:2022 / NĐ 136/2020)

Tables:
  * fire_certs              — certification header (design or acceptance)
  * fire_inspections        — physical inspection rounds
  * fire_checklist_items    — QCVN 06:2022 design checklist

Revision ID: 0045_pccc
Revises: 0044_thanhtoan
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0045_pccc"
down_revision = "0044_thanhtoan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fire_certs",
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
        sa.Column("cert_type", sa.Text(), nullable=False),
        sa.Column("reference_no", sa.Text(), nullable=False),
        sa.Column("hazard_category", sa.Text(), nullable=False),
        sa.Column("building_class", sa.Text(), nullable=False),
        sa.Column("height_m", sa.Numeric(8, 2)),
        sa.Column("floors_above", sa.Integer()),
        sa.Column("floors_below", sa.Integer()),
        sa.Column("area_sqm", sa.Numeric(12, 2)),
        sa.Column("occupant_load", sa.Integer()),
        sa.Column("pc07_unit", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="planning"),
        sa.Column("submitted_date", sa.Date()),
        sa.Column("inspection_date", sa.Date()),
        sa.Column("decision_date", sa.Date()),
        sa.Column("decision_number", sa.Text()),
        sa.Column(
            "decision_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "legal_basis",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
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
        sa.UniqueConstraint(
            "project_id", "cert_type", "reference_no", name="uq_fire_certs_project_type_ref"
        ),
        sa.CheckConstraint(
            "cert_type IN ('design', 'acceptance', 'recert')",
            name="ck_fire_certs_type",
        ),
        sa.CheckConstraint(
            "hazard_category IN ('A', 'B', 'C', 'D', 'E', 'F')",
            name="ck_fire_certs_hazard",
        ),
        sa.CheckConstraint(
            "building_class IN ('CO1', 'CO2', 'CO3', 'CO4')",
            name="ck_fire_certs_building_class",
        ),
        sa.CheckConstraint(
            "status IN ('planning', 'submitted', 'inspection_scheduled', 'rfi', "
            "'approved', 'conditional', 'rejected', 'expired')",
            name="ck_fire_certs_status",
        ),
    )
    op.create_index("ix_fire_certs_project", "fire_certs", ["organization_id", "project_id"])
    op.create_index("ix_fire_certs_status", "fire_certs", ["organization_id", "status"])
    op.create_index(
        "ix_fire_certs_expiry",
        "fire_certs",
        ["organization_id", "expiry_date"],
        postgresql_where=sa.text("status = 'approved' AND expiry_date IS NOT NULL"),
    )

    op.create_table(
        "fire_inspections",
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
            "cert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fire_certs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("inspection_date", sa.Date(), nullable=False),
        sa.Column("inspector_name", sa.Text(), nullable=False),
        sa.Column("inspector_org", sa.Text()),
        sa.Column("overall_result", sa.Text(), nullable=False, server_default="rescheduled"),
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("summary", sa.Text()),
        sa.Column("next_steps", sa.Text()),
        sa.Column(
            "report_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("cert_id", "round_number", name="uq_fire_inspections_cert_round"),
        sa.CheckConstraint(
            "overall_result IN ('pass', 'conditional_pass', 'fail', 'rescheduled')",
            name="ck_fire_inspections_result",
        ),
    )
    op.create_index("ix_fire_inspections_cert", "fire_inspections", ["cert_id", "round_number"])

    op.create_table(
        "fire_checklist_items",
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
            "cert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fire_certs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clause_ref", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reviewer_note", sa.Text()),
        sa.Column(
            "reviewer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "evidence_file_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column(
            "drawing_refs",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("severity", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
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
        sa.CheckConstraint(
            "status IN ('pending', 'compliant', 'non_compliant', 'not_applicable')",
            name="ck_fire_checklist_items_status",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'minor', 'medium', 'major', 'critical')",
            name="ck_fire_checklist_items_severity",
        ),
    )
    op.create_index(
        "ix_fire_checklist_items_cert",
        "fire_checklist_items",
        ["cert_id", "sort_order"],
    )
    op.create_index(
        "ix_fire_checklist_items_status",
        "fire_checklist_items",
        ["organization_id", "status"],
    )

    for table in ("fire_certs", "fire_inspections", "fire_checklist_items"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("fire_checklist_items", "fire_inspections", "fire_certs"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
