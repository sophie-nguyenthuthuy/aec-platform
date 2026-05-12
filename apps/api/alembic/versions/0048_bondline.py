"""bondline tables — VN bank-issued bonds

Tables:
  * bonds        — bid / performance / advance / warranty bonds
  * bond_claims  — claim / extension / cancellation requests

Revision ID: 0048_bondline
Revises: 0047_greenmark
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048_bondline"
down_revision = "0047_greenmark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bonds",
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
        sa.Column("bond_type", sa.Text(), nullable=False),
        sa.Column("bond_no", sa.Text(), nullable=False),
        sa.Column("issuing_bank", sa.Text(), nullable=False),
        sa.Column("bank_branch", sa.Text()),
        sa.Column("beneficiary_name", sa.Text(), nullable=False),
        sa.Column("beneficiary_mst", sa.Text()),
        sa.Column("face_amount_vnd", sa.BigInteger(), nullable=False),
        sa.Column("contract_value_vnd", sa.BigInteger()),
        sa.Column("coverage_pct", sa.Numeric(5, 4)),
        sa.Column("currency", sa.Text(), nullable=False, server_default="VND"),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("effective_date", sa.Date()),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("released_at", sa.Date()),
        sa.Column("released_reason", sa.Text()),
        sa.Column(
            "bond_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column("contract_no", sa.Text()),
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
        sa.UniqueConstraint(
            "organization_id", "issuing_bank", "bond_no", name="uq_bonds_org_bank_no"
        ),
        sa.CheckConstraint(
            "bond_type IN ('bid', 'performance', 'advance', 'warranty')",
            name="ck_bonds_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'released', 'claimed', 'expired', 'cancelled')",
            name="ck_bonds_status",
        ),
        sa.CheckConstraint(
            "face_amount_vnd >= 0", name="ck_bonds_face_amount_nonneg"
        ),
        sa.CheckConstraint("expiry_date > issue_date", name="ck_bonds_expiry_after_issue"),
    )
    op.create_index("ix_bonds_project", "bonds", ["organization_id", "project_id"])
    op.create_index("ix_bonds_status", "bonds", ["organization_id", "status"])
    op.create_index(
        "ix_bonds_expiry",
        "bonds",
        ["organization_id", "expiry_date"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "bond_claims",
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
            "bond_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bonds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claim_type", sa.Text(), nullable=False),
        sa.Column("claim_amount_vnd", sa.BigInteger()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("decided_date", sa.Date()),
        sa.Column("decided_amount_vnd", sa.BigInteger()),
        sa.Column("reason", sa.Text()),
        sa.Column("decision_note", sa.Text()),
        sa.Column(
            "evidence_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
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
        sa.CheckConstraint(
            "claim_type IN ('default_call', 'extension', 'amount_increase', 'cancellation')",
            name="ck_bond_claims_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'partial', 'rejected', 'withdrawn')",
            name="ck_bond_claims_status",
        ),
    )
    op.create_index("ix_bond_claims_bond", "bond_claims", ["bond_id", "filed_date"])

    for table in ("bonds", "bond_claims"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("bond_claims", "bonds"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
