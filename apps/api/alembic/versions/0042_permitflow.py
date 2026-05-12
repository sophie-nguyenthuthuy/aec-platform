"""permitflow tables — VN construction permit chain

Tables:
  * permit_dossiers     — one row per project block / phase
  * permit_stages       — five rows per dossier (chủ trương đầu tư …
                          nghiệm thu PCCC)
  * permit_submissions  — round-trips with the issuing authority

RLS: tenant-scoped via `app.current_org_id`, USING + WITH CHECK from
the start (per the 0021 audit pattern).

Revision ID: 0042_permitflow
Revises: 0041_gemini_embedding_dim
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042_permitflow"
down_revision = "0041_gemini_embedding_dim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- permit_dossiers ----------
    op.create_table(
        "permit_dossiers",
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
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("investment_type", sa.Text(), nullable=False, server_default="domestic"),
        sa.Column("status", sa.Text(), nullable=False, server_default="planning"),
        sa.Column(
            "location",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "land_cert_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column("land_parcel_no", sa.Text()),
        sa.Column("notes", sa.Text()),
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
        # Permit chain status values are bounded — keep the runtime
        # guard close to the data rather than relying solely on the
        # Pydantic enum.
        sa.CheckConstraint(
            "status IN ('planning', 'in_progress', 'on_hold', 'completed', 'cancelled')",
            name="ck_permit_dossiers_status",
        ),
        sa.CheckConstraint(
            "classification IN ('cap_iv', 'cap_iii', 'cap_ii', 'cap_i', 'dac_biet')",
            name="ck_permit_dossiers_classification",
        ),
        sa.CheckConstraint(
            "investment_type IN ('domestic', 'fdi')",
            name="ck_permit_dossiers_investment_type",
        ),
    )
    op.create_index(
        "ix_permit_dossiers_org_project",
        "permit_dossiers",
        ["organization_id", "project_id"],
    )
    op.create_index(
        "ix_permit_dossiers_status",
        "permit_dossiers",
        ["organization_id", "status"],
    )

    # ---------- permit_stages ----------
    op.create_table(
        "permit_stages",
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
            "dossier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("permit_dossiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_code", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="not_started"),
        sa.Column(
            "legal_basis",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("target_submit_date", sa.Date()),
        sa.Column("submitted_date", sa.Date()),
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
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("dossier_id", "stage_code", name="uq_permit_stages_dossier_stage"),
        sa.CheckConstraint(
            "stage_code IN ('chu_truong_dau_tu', 'quy_hoach_1_500', 'tham_dinh_tkcs', "
            "'gpxd', 'nghiem_thu_pccc')",
            name="ck_permit_stages_stage_code",
        ),
        sa.CheckConstraint(
            "status IN ('not_started', 'preparing', 'submitted', 'in_review', 'rfi', "
            "'approved', 'rejected', 'withdrawn', 'expired')",
            name="ck_permit_stages_status",
        ),
        sa.CheckConstraint(
            "authority IN ('BKHDT', 'BXD', 'UBND_TINH', 'UBND_HUYEN', 'SXD', 'PC07')",
            name="ck_permit_stages_authority",
        ),
        sa.CheckConstraint("sequence BETWEEN 1 AND 5", name="ck_permit_stages_sequence"),
    )
    op.create_index(
        "ix_permit_stages_dossier_seq",
        "permit_stages",
        ["dossier_id", "sequence"],
    )
    op.create_index(
        "ix_permit_stages_status",
        "permit_stages",
        ["organization_id", "status"],
    )
    # Partial index for the alerts cron — only approved stages with a
    # statutory expiry need the lookup, so the index pays for itself
    # only when populated by the (rare) approved row.
    op.create_index(
        "ix_permit_stages_expiry",
        "permit_stages",
        ["organization_id", "expiry_date"],
        postgresql_where=sa.text("status = 'approved' AND expiry_date IS NOT NULL"),
    )

    # ---------- permit_submissions ----------
    op.create_table(
        "permit_submissions",
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
            "stage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("permit_stages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("submission_type", sa.Text(), nullable=False, server_default="initial"),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("receipt_number", sa.Text()),
        sa.Column(
            "package_file_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("outcome", sa.Text()),
        sa.Column("outcome_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("outcome_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("stage_id", "round_number", name="uq_permit_submissions_stage_round"),
        sa.CheckConstraint(
            "submission_type IN ('initial', 'rfi_response', 'resubmission', 'withdrawal_request')",
            name="ck_permit_submissions_type",
        ),
        sa.CheckConstraint(
            "outcome_status IN ('pending', 'accepted', 'rfi_issued', 'rejected')",
            name="ck_permit_submissions_outcome_status",
        ),
        sa.CheckConstraint("round_number >= 1", name="ck_permit_submissions_round_number"),
    )
    op.create_index(
        "ix_permit_submissions_stage",
        "permit_submissions",
        ["stage_id", "round_number"],
    )
    op.create_index(
        "ix_permit_submissions_outcome",
        "permit_submissions",
        ["organization_id", "outcome_status"],
    )

    # ---------- RLS ----------
    for table in ("permit_dossiers", "permit_stages", "permit_submissions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("permit_submissions", "permit_stages", "permit_dossiers"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
