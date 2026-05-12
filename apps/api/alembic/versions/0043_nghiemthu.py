"""nghiemthu tables — statutory acceptance per NĐ 06/2021/NĐ-CP

Tables:
  * acceptance_records      — biên bản nghiệm thu (BBNT) header
  * acceptance_signatories  — CĐT / TVGS / NT (+optional) signoffs
  * acceptance_evidence     — photos, test certs, dailylog refs

RLS: tenant-scoped via `app.current_org_id`, USING + WITH CHECK.

Revision ID: 0043_nghiemthu
Revises: 0042_permitflow
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0043_nghiemthu"
down_revision = "0042_permitflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- acceptance_records ----------
    op.create_table(
        "acceptance_records",
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
        sa.Column("reference_no", sa.Text(), nullable=False),
        sa.Column("acceptance_level", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("acceptance_date", sa.Date(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column(
            "work_item_codes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "quantities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "basis",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("conclusion", sa.Text()),
        sa.Column(
            "pdf_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        # Self-FK; ondelete SET NULL because we want to keep the
        # superseded original alive even if the replacement is purged.
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("acceptance_records.id", ondelete="SET NULL"),
        ),
        sa.Column("finalized_at", sa.TIMESTAMP(timezone=True)),
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
        sa.CheckConstraint(
            "acceptance_level IN ('cong_viec', 'giai_doan', 'hoan_thanh')",
            name="ck_acceptance_records_level",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_signoff', 'accepted', 'rejected', 'superseded')",
            name="ck_acceptance_records_status",
        ),
    )
    op.create_index(
        "ix_acceptance_records_project_level",
        "acceptance_records",
        ["organization_id", "project_id", "acceptance_level"],
    )
    op.create_index(
        "ix_acceptance_records_status",
        "acceptance_records",
        ["organization_id", "status"],
    )
    # GIN on the BoQ code array — supports the "find BBNTs touching
    # work item X" lookup used by costpulse drilldowns.
    op.create_index(
        "ix_acceptance_records_work_codes",
        "acceptance_records",
        ["work_item_codes"],
        postgresql_using="gin",
    )

    # ---------- acceptance_signatories ----------
    op.create_table(
        "acceptance_signatories",
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
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("acceptance_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("org_name", sa.Text(), nullable=False),
        sa.Column("representative_name", sa.Text(), nullable=False),
        sa.Column("position", sa.Text()),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("decision", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("comment", sa.Text()),
        sa.Column("signed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "signature_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "signed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "record_id", "role", "org_name", name="uq_acceptance_signatories_record_party"
        ),
        sa.CheckConstraint(
            "role IN ('cdt', 'tvgs', 'nt', 'tvtk', 'tvqlda')",
            name="ck_acceptance_signatories_role",
        ),
        sa.CheckConstraint(
            "decision IN ('pending', 'approve', 'reject', 'comment_only')",
            name="ck_acceptance_signatories_decision",
        ),
    )
    op.create_index(
        "ix_acceptance_signatories_record",
        "acceptance_signatories",
        ["record_id", "sort_order"],
    )

    # ---------- acceptance_evidence ----------
    op.create_table(
        "acceptance_evidence",
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
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("acceptance_records.id", ondelete="CASCADE"),
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
        sa.Column("captured_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "kind IN ('photo', 'document', 'test_cert', 'drawing_ref', "
            "'dailylog_ref', 'task_ref')",
            name="ck_acceptance_evidence_kind",
        ),
        sa.CheckConstraint(
            "file_id IS NOT NULL OR external_ref IS NOT NULL",
            name="ck_acceptance_evidence_has_pointer",
        ),
    )
    op.create_index(
        "ix_acceptance_evidence_record",
        "acceptance_evidence",
        ["record_id", "sort_order"],
    )

    # ---------- RLS ----------
    for table in ("acceptance_records", "acceptance_signatories", "acceptance_evidence"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("acceptance_evidence", "acceptance_signatories", "acceptance_records"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
