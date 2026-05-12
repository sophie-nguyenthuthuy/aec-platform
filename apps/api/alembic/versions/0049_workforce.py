"""workforce tables — VN labor records

Tables:
  * workers                       — identity per individual (org-scoped)
  * worker_safety_trainings       — ATLD (NĐ 44/2016) records
  * worker_insurance_enrollments  — BHXH/BHYT/BHTN history
  * foreign_worker_permits        — NĐ 152/2020 work permits
  * project_worker_assignments    — worker × project links

Revision ID: 0049_workforce
Revises: 0048_bondline
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049_workforce"
down_revision = "0048_bondline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workers",
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
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("dob", sa.Date()),
        sa.Column("gender", sa.Text()),
        sa.Column("id_no", sa.Text()),
        sa.Column("id_issued_date", sa.Date()),
        sa.Column("id_issued_place", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("trade", sa.Text(), nullable=False),
        sa.Column("employment_type", sa.Text(), nullable=False, server_default="direct"),
        sa.Column("employer_org_name", sa.Text()),
        sa.Column("nationality", sa.Text(), nullable=False, server_default="VN"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("hire_date", sa.Date()),
        sa.Column("termination_date", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("organization_id", "id_no", name="uq_workers_org_id_no"),
        sa.CheckConstraint(
            "employment_type IN ('direct', 'subcontractor', 'temporary', 'foreign')",
            name="ck_workers_employment_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'terminated')",
            name="ck_workers_status",
        ),
        sa.CheckConstraint(
            "id_no IS NULL OR id_no ~ '^\\d{9}$|^\\d{12}$'",
            name="ck_workers_id_no_format",
        ),
    )
    op.create_index("ix_workers_org_status", "workers", ["organization_id", "status"])
    op.create_index(
        "ix_workers_trade", "workers", ["organization_id", "trade"]
    )
    op.create_index(
        "ix_workers_name_search",
        "workers",
        ["organization_id", "full_name"],
    )

    op.create_table(
        "worker_safety_trainings",
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
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group", sa.Text(), nullable=False),
        sa.Column("training_org", sa.Text(), nullable=False),
        sa.Column("training_date", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("certificate_no", sa.Text()),
        sa.Column(
            "certificate_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="valid"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "\"group\" IN ('1', '2', '3', '4', '5', '6')",
            name="ck_worker_safety_trainings_group",
        ),
        sa.CheckConstraint(
            "status IN ('valid', 'expired', 'revoked')",
            name="ck_worker_safety_trainings_status",
        ),
        sa.CheckConstraint(
            "valid_until > training_date",
            name="ck_worker_safety_trainings_valid_after_training",
        ),
    )
    op.create_index(
        "ix_worker_safety_trainings_worker",
        "worker_safety_trainings",
        ["worker_id", "training_date"],
    )
    op.create_index(
        "ix_worker_safety_trainings_expiry",
        "worker_safety_trainings",
        ["organization_id", "valid_until"],
        postgresql_where=sa.text("status = 'valid'"),
    )

    op.create_table(
        "worker_insurance_enrollments",
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
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("basic_salary_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bhxh_enrolled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("bhyt_enrolled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("bhtn_enrolled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("bhxh_no", sa.Text()),
        sa.Column("enrolled_at", sa.Date()),
        sa.Column("terminated_at", sa.Date()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("worker_insurance_enrollments.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "status IN ('enrolled', 'pending', 'not_required', 'terminated', 'superseded')",
            name="ck_worker_insurance_enrollments_status",
        ),
        sa.CheckConstraint(
            "basic_salary_vnd >= 0",
            name="ck_worker_insurance_enrollments_salary_nonneg",
        ),
    )
    op.create_index(
        "ix_worker_insurance_active",
        "worker_insurance_enrollments",
        ["worker_id"],
        postgresql_where=sa.text("status = 'enrolled'"),
    )

    op.create_table(
        "foreign_worker_permits",
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
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nationality", sa.Text(), nullable=False),
        sa.Column("passport_no", sa.Text(), nullable=False),
        sa.Column("job_position", sa.Text(), nullable=False),
        sa.Column("permit_no", sa.Text()),
        sa.Column("issue_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("exemption_type", sa.Text(), nullable=False, server_default="required"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "permit_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "exemption_type IN ('required', 'exempt_short_term', 'exempt_intracompany', 'exempt_other')",
            name="ck_foreign_worker_permits_exemption",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="ck_foreign_worker_permits_status",
        ),
    )
    op.create_index(
        "ix_foreign_worker_permits_expiry",
        "foreign_worker_permits",
        ["organization_id", "expiry_date"],
        postgresql_where=sa.text("status = 'approved' AND expiry_date IS NOT NULL"),
    )

    op.create_table(
        "project_worker_assignments",
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
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role_on_project", sa.Text()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint(
            "worker_id", "project_id", "start_date",
            name="uq_project_worker_assignments_worker_project_start",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'ended', 'cancelled')",
            name="ck_project_worker_assignments_status",
        ),
    )
    op.create_index(
        "ix_project_worker_assignments_project",
        "project_worker_assignments",
        ["project_id", "status"],
    )

    for table in (
        "workers",
        "worker_safety_trainings",
        "worker_insurance_enrollments",
        "foreign_worker_permits",
        "project_worker_assignments",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in (
        "project_worker_assignments",
        "foreign_worker_permits",
        "worker_insurance_enrollments",
        "worker_safety_trainings",
        "workers",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
