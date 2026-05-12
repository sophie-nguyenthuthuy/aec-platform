"""thanhtoan tables — progress payment claims with VN tax math

Tables:
  * payment_claims          — header (totals + signoff timestamps)
  * payment_claim_lines     — per work-item rows
  * payment_claim_evidence  — cover-level attachments

Money columns are BIGINT VND (no fractions); percentage columns are
NUMERIC(5,4) so 8% stores as 0.0800.

Revision ID: 0044_thanhtoan
Revises: 0043_nghiemthu
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0044_thanhtoan"
down_revision = "0043_nghiemthu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- payment_claims ----------
    op.create_table(
        "payment_claims",
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
        sa.Column("claim_no", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("subtotal_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("vat_pct", sa.Numeric(5, 4), nullable=False, server_default="0.0800"),
        sa.Column("vat_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("gross_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("retention_pct", sa.Numeric(5, 4), nullable=False, server_default="0.0500"),
        sa.Column("retention_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tndn_pct", sa.Numeric(5, 4), nullable=False, server_default="0.0100"),
        sa.Column("tndn_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("net_payable_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cumulative_prev_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("cdt_signed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "cdt_signed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("cdt_decision", sa.Text()),
        sa.Column("cdt_comment", sa.Text()),
        sa.Column("tvgs_signed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "tvgs_signed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("tvgs_decision", sa.Text()),
        sa.Column("tvgs_comment", sa.Text()),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("rejected_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("due_at", sa.Date()),
        sa.Column("paid_at", sa.Date()),
        sa.Column("payment_reference", sa.Text()),
        sa.Column(
            "pdf_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("project_id", "claim_no", name="uq_payment_claims_project_claim_no"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'in_review', 'approved', 'rejected', 'paid', 'cancelled')",
            name="ck_payment_claims_status",
        ),
        sa.CheckConstraint(
            "cdt_decision IS NULL OR cdt_decision IN ('approve', 'reject')",
            name="ck_payment_claims_cdt_decision",
        ),
        sa.CheckConstraint(
            "tvgs_decision IS NULL OR tvgs_decision IN ('approve', 'reject')",
            name="ck_payment_claims_tvgs_decision",
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_payment_claims_period"),
        # Money columns must be non-negative — typo guard.
        sa.CheckConstraint(
            "subtotal_vnd >= 0 AND vat_vnd >= 0 AND gross_vnd >= 0 "
            "AND retention_vnd >= 0 AND tndn_vnd >= 0 AND net_payable_vnd >= 0",
            name="ck_payment_claims_amounts_nonneg",
        ),
    )
    op.create_index(
        "ix_payment_claims_project_period",
        "payment_claims",
        ["project_id", "period_end"],
    )
    op.create_index(
        "ix_payment_claims_status",
        "payment_claims",
        ["organization_id", "status"],
    )
    # Partial index supports the "due in N days" alert lane.
    op.create_index(
        "ix_payment_claims_due",
        "payment_claims",
        ["organization_id", "due_at"],
        postgresql_where=sa.text("status IN ('approved', 'in_review') AND due_at IS NOT NULL"),
    )

    # ---------- payment_claim_lines ----------
    op.create_table(
        "payment_claim_lines",
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
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("work_item_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("planned_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("this_period_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("cumulative_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_rate_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("this_period_amount_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cumulative_amount_vnd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("completion_pct", sa.Numeric(7, 4)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "evidence_file_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("claim_id", "work_item_code", name="uq_payment_claim_lines_claim_workitem"),
        sa.CheckConstraint(
            "this_period_qty >= 0 AND cumulative_qty >= 0 AND unit_rate_vnd >= 0",
            name="ck_payment_claim_lines_nonneg",
        ),
    )
    op.create_index(
        "ix_payment_claim_lines_claim",
        "payment_claim_lines",
        ["claim_id", "sort_order"],
    )
    op.create_index(
        "ix_payment_claim_lines_workitem",
        "payment_claim_lines",
        ["organization_id", "work_item_code"],
    )

    # ---------- payment_claim_evidence ----------
    op.create_table(
        "payment_claim_evidence",
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
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column("external_ref", sa.Text()),
        sa.Column("caption", sa.Text()),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "kind IN ('photo', 'document', 'invoice', 'test_cert', "
            "'dailylog_ref', 'nghiemthu_ref')",
            name="ck_payment_claim_evidence_kind",
        ),
        sa.CheckConstraint(
            "file_id IS NOT NULL OR external_ref IS NOT NULL",
            name="ck_payment_claim_evidence_has_pointer",
        ),
    )
    op.create_index(
        "ix_payment_claim_evidence_claim",
        "payment_claim_evidence",
        ["claim_id", "sort_order"],
    )

    # ---------- RLS ----------
    for table in ("payment_claims", "payment_claim_lines", "payment_claim_evidence"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("payment_claim_evidence", "payment_claim_lines", "payment_claims"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
