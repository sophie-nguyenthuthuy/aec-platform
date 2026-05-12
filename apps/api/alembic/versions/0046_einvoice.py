"""einvoice tables — HĐĐT per NĐ 123/2020 + TT 78/2021

Tables:
  * einvoices            — invoice header (tenant-scoped, RLS)
  * einvoice_lines       — line items (tenant-scoped, RLS)
  * tax_id_validations   — MST validation cache (GLOBAL — no RLS)

Revision ID: 0046_einvoice
Revises: 0045_pccc
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046_einvoice"
down_revision = "0045_pccc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- einvoices ----------
    op.create_table(
        "einvoices",
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
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
        ),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("invoice_no", sa.Text(), nullable=False),
        sa.Column("template_no", sa.Text(), nullable=False),
        sa.Column("serial_no", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("issuer_mst", sa.Text(), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("issuer_address", sa.Text()),
        sa.Column("issuer_bank_account", sa.Text()),
        sa.Column("buyer_mst", sa.Text()),
        sa.Column("buyer_name", sa.Text(), nullable=False),
        sa.Column("buyer_address", sa.Text()),
        sa.Column("buyer_email", sa.Text()),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("paid_at", sa.Date()),
        sa.Column("currency", sa.Text(), nullable=False, server_default="VND"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("subtotal", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "vat_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("vat_total", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("gdt_code", sa.Text()),
        sa.Column("gdt_submitted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("gdt_accepted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("gdt_rejection_reason", sa.Text()),
        sa.Column("payment_method", sa.Text()),
        sa.Column("payment_reference", sa.Text()),
        sa.Column(
            "adjustment_for_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("einvoices.id", ondelete="SET NULL"),
        ),
        sa.Column("adjustment_reason", sa.Text()),
        sa.Column(
            "xml_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint(
            "issuer_mst",
            "template_no",
            "serial_no",
            "invoice_no",
            name="uq_einvoices_issuer_template_serial_no",
        ),
        sa.CheckConstraint(
            "direction IN ('issued', 'received')",
            name="ck_einvoices_direction",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'submitted_gdt', 'accepted_gdt', "
            "'rejected_gdt', 'cancelled', 'adjustment_issued')",
            name="ck_einvoices_status",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND vat_total >= 0 AND total >= 0",
            name="ck_einvoices_amounts_nonneg",
        ),
        sa.CheckConstraint(
            "exchange_rate > 0",
            name="ck_einvoices_exchange_rate_positive",
        ),
    )
    op.create_index(
        "ix_einvoices_org_issue",
        "einvoices",
        ["organization_id", "issue_date"],
    )
    op.create_index(
        "ix_einvoices_status",
        "einvoices",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_einvoices_project",
        "einvoices",
        ["organization_id", "project_id"],
    )
    op.create_index(
        "ix_einvoices_buyer_mst",
        "einvoices",
        ["organization_id", "buyer_mst"],
        postgresql_where=sa.text("buyer_mst IS NOT NULL"),
    )

    # ---------- einvoice_lines ----------
    op.create_table(
        "einvoice_lines",
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
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("einvoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("item_code", sa.Text()),
        sa.Column("unit", sa.Text(), nullable=False, server_default="cái"),
        sa.Column("qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("discount_pct", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("line_total", sa.BigInteger(), nullable=False, server_default="0"),
        # NULL = exempt; standard rates 0/0.05/0.08/0.10.
        sa.Column("vat_rate", sa.Numeric(5, 4)),
        sa.Column("vat_amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "qty >= 0 AND unit_price >= 0 AND line_total >= 0 AND vat_amount >= 0",
            name="ck_einvoice_lines_nonneg",
        ),
        sa.CheckConstraint(
            "vat_rate IS NULL OR vat_rate IN (0.0, 0.05, 0.08, 0.10)",
            name="ck_einvoice_lines_vat_rate_known",
        ),
        sa.CheckConstraint(
            "discount_pct >= 0 AND discount_pct <= 1",
            name="ck_einvoice_lines_discount_range",
        ),
    )
    op.create_index(
        "ix_einvoice_lines_invoice",
        "einvoice_lines",
        ["invoice_id", "sort_order"],
    )

    # ---------- tax_id_validations (GLOBAL, no RLS) ----------
    op.create_table(
        "tax_id_validations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mst", sa.Text(), nullable=False, unique=True),
        sa.Column("gdt_status", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("registered_at", sa.Date()),
        sa.Column("business_type", sa.Text()),
        sa.Column(
            "last_checked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "raw_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "gdt_status IN ('active', 'suspended', 'closed', 'not_found')",
            name="ck_tax_id_validations_status",
        ),
    )
    op.create_index(
        "ix_tax_id_validations_last_checked",
        "tax_id_validations",
        ["last_checked_at"],
    )

    # ---------- RLS (only on the per-tenant tables) ----------
    for table in ("einvoices", "einvoice_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("tax_id_validations", "einvoice_lines", "einvoices"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
