"""CashFlow — Dòng tiền dự án.

Two tables track expected cash movements for a project:

  * `cashflow_entries` — one row per scheduled inflow or outflow.
    `kind=inflow` is money the customer owes us (linked to a Pulse
    milestone for "completion of phase X triggers 30% invoice");
    `kind=outflow` is money we owe (subcontractor advance, material
    invoice, …).
  * `cashflow_actuals` — paired actuals when payments materialise.
    Lets the forecast surface drift between expected and actual.

Why a new module instead of extending Pulse milestones / Costpulse
estimates: cashflow planning is its own discipline (PM doesn't manage
it, the project controller does). Owning a dedicated table keeps
status filters + dashboards uncluttered.

Revision ID: 0052_cashflow
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052_cashflow"
down_revision: Union[str, None] = "0051_llm_spend"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "cashflow_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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
        # inflow (Bên A trả ta) | outflow (ta trả Bên B)
        sa.Column("kind", sa.Text, nullable=False),
        # short human label e.g. "Thanh toán 30% sau khi nghiệm thu kết cấu"
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("amount_vnd", sa.BigInteger, nullable=False),
        # expected date the cash should move
        sa.Column("expected_date", sa.Date, nullable=False),
        # optional milestone link (only for inflows tied to Pulse milestones)
        sa.Column(
            "milestone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("milestones.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # optional supplier link for outflows (cross-module ref into costpulse.suppliers)
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # planned | committed | invoiced | paid | overdue | cancelled
        sa.Column("status", sa.Text, nullable=False, server_default="planned"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('inflow', 'outflow')",
            name="ck_cashflow_entries_kind",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'committed', 'invoiced', 'paid', 'overdue', 'cancelled')",
            name="ck_cashflow_entries_status",
        ),
        sa.CheckConstraint(
            "amount_vnd >= 0",
            name="ck_cashflow_entries_amount_nonneg",
        ),
    )
    op.create_index(
        "ix_cashflow_org_project_date",
        "cashflow_entries",
        ["organization_id", "project_id", "expected_date"],
    )

    op.create_table(
        "cashflow_actuals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cashflow_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_vnd", sa.BigInteger, nullable=False),
        sa.Column("paid_on", sa.Date, nullable=False),
        sa.Column("reference", sa.Text, nullable=True),  # bank ref / hoá đơn số
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "recorded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_cashflow_actuals_entry_paid",
        "cashflow_actuals",
        ["entry_id", "paid_on"],
    )

    # ---- RLS ----
    # Both tables get standard tenant isolation against the per-request
    # `app.current_org_id` GUC pinned by TenantAwareSession.
    for table in ("cashflow_entries", "cashflow_actuals"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table}
              ON {table}
              USING (organization_id = current_setting('app.current_org_id', true)::uuid)
              WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("cashflow_actuals")
    op.drop_table("cashflow_entries")
