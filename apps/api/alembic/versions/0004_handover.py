"""handover tables

Revision ID: 0004_handover
Revises: 0003_siteeye
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_handover"
down_revision = "0003_siteeye"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "handover_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("scope_summary", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("export_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_handover_packages_project", "handover_packages", ["organization_id", "project_id"])
    op.create_index("ix_handover_packages_status", "handover_packages", ["organization_id", "status"])

    op.create_table(
        "closeout_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("handover_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("file_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("notes", sa.Text()),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_closeout_items_package", "closeout_items", ["package_id", "sort_order"])
    op.create_index("ix_closeout_items_status", "closeout_items", ["package_id", "status"])

    op.create_table(
        "as_built_drawings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("handover_packages.id", ondelete="SET NULL")),
        sa.Column("drawing_code", sa.Text(), nullable=False),
        sa.Column("discipline", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("current_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("superseded_file_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("changelog", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "drawing_code", name="uq_as_built_drawings_project_code"),
    )
    op.create_index("ix_as_built_project", "as_built_drawings", ["organization_id", "project_id"])
    op.create_index("ix_as_built_discipline", "as_built_drawings", ["project_id", "discipline"])

    op.create_table(
        "om_manuals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("handover_packages.id", ondelete="CASCADE")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("discipline", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("equipment", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("maintenance_schedule", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_file_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("pdf_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("ai_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_jobs.id", ondelete="SET NULL")),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_om_manuals_package", "om_manuals", ["package_id"])
    op.create_index("ix_om_manuals_project", "om_manuals", ["organization_id", "project_id"])

    op.create_table(
        "warranty_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("handover_packages.id", ondelete="SET NULL")),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text()),
        sa.Column("vendor", sa.Text()),
        sa.Column("contract_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("warranty_period_months", sa.Integer()),
        sa.Column("start_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("coverage", sa.Text()),
        sa.Column("claim_contact", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_warranty_items_project", "warranty_items", ["organization_id", "project_id"])
    op.create_index("ix_warranty_items_expiry", "warranty_items", ["expiry_date"])
    op.create_index("ix_warranty_items_status", "warranty_items", ["status"])

    op.create_table(
        "defects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("handover_packages.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("location", postgresql.JSONB()),
        sa.Column("photo_file_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("priority", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reported_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reported_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("resolution_notes", sa.Text()),
    )
    op.create_index("ix_defects_project", "defects", ["organization_id", "project_id"])
    op.create_index("ix_defects_package", "defects", ["package_id"])
    op.create_index("ix_defects_status", "defects", ["status"])
    op.create_index("ix_defects_assignee", "defects", ["assignee_id"])

    for table in (
        "handover_packages",
        "closeout_items",
        "as_built_drawings",
        "om_manuals",
        "warranty_items",
        "defects",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in (
        "defects",
        "warranty_items",
        "om_manuals",
        "as_built_drawings",
        "closeout_items",
        "handover_packages",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
