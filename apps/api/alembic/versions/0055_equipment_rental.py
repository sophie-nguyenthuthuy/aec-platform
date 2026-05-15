"""EquipmentRental — Máy thi công thuê.

Universal VN-construction pain: mỗi dự án thuê 5-20 máy (cần cẩu,
máy đào, máy bơm bê tông, máy phát điện), mỗi máy 500.000 — 5.000.000
VNĐ/ngày. Hiện theo dõi qua Excel rời rạc, không ai biết utilization
thực tế vs hợp đồng → khách hàng bị "tính khống" ngày không sử dụng.

Schema:
  * `equipment_rentals` — hợp đồng thuê máy. Bao gồm loại máy, NCC,
    rate VNĐ/ngày, thời gian dự kiến + thực tế.
  * `equipment_rental_logs` — nhật ký sử dụng theo ngày. Hỗ trợ
    `used / idle / maintenance / off` để phản ánh thực tế (máy có
    ở site nhưng không hoạt động vẫn tính tiền).
  * `equipment_rental_invoices` — đối chiếu hoá đơn NCC với log
    thực tế. Phát hiện chênh lệch.

Cross-module:
  * Optional FK to cashflow_entries (outflow rental cost forecast).
  * Optional FK to projects + schedule_activities (activity-level
    equipment utilization).

Revision ID: 0055_equipment_rental
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_equipment_rental"
down_revision: Union[str, None] = "0054_subcontractor_portal"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "equipment_rentals",
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
        # equipment_type slugs cover the common VN-site categories. Free-text
        # `equipment_name` for variation ("Cẩu tháp TC5610" vs "Cẩu tháp 5T").
        sa.Column("equipment_type", sa.Text, nullable=False),
        sa.Column("equipment_name", sa.Text, nullable=False),
        sa.Column("equipment_serial", sa.Text, nullable=True),
        # supplier — text field for early launch, link to suppliers table later
        sa.Column("supplier_name", sa.Text, nullable=False),
        sa.Column("supplier_phone", sa.Text, nullable=True),
        sa.Column("contract_number", sa.Text, nullable=True),
        # rate_vnd_per_day — base rental rate. weekly_discount + monthly_discount
        # as JSONB so we can model "thuê >= 30 ngày = -15%" tier deals.
        sa.Column("rate_vnd_per_day", sa.BigInteger, nullable=False),
        sa.Column("rate_tier", postgresql.JSONB, nullable=True),
        sa.Column("planned_start", sa.Date, nullable=False),
        sa.Column("planned_finish", sa.Date, nullable=False),
        sa.Column("actual_start", sa.Date, nullable=True),
        sa.Column("actual_finish", sa.Date, nullable=True),
        # planned | active | returned | cancelled
        sa.Column("status", sa.Text, nullable=False, server_default="planned"),
        # Operator-provided notes — site-specific notes, equipment ID, etc.
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
            "status IN ('planned', 'active', 'returned', 'cancelled')",
            name="ck_equipment_rentals_status",
        ),
        sa.CheckConstraint(
            "rate_vnd_per_day >= 0",
            name="ck_equipment_rentals_rate_nonneg",
        ),
        sa.CheckConstraint(
            "planned_finish >= planned_start",
            name="ck_equipment_rentals_planned_dates",
        ),
    )
    op.create_index(
        "ix_equipment_rentals_project",
        "equipment_rentals",
        ["project_id"],
    )

    op.create_table(
        "equipment_rental_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rental_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipment_rentals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("log_date", sa.Date, nullable=False),
        # used = máy hoạt động full ngày
        # idle = máy ở site nhưng không hoạt động (vẫn tính tiền theo HĐ)
        # maintenance = đang sửa chữa (NCC thường miễn phí ngày này)
        # off = NCC chưa giao máy / đã thu hồi (không tính tiền)
        sa.Column("usage_state", sa.Text, nullable=False),
        sa.Column("hours_operated", sa.Numeric(5, 1), nullable=True),
        # operator info — driver name + phone
        sa.Column("operator_name", sa.Text, nullable=True),
        sa.Column("operator_phone", sa.Text, nullable=True),
        # fuel cost if site supplies fuel (đa số VN-site)
        sa.Column("fuel_cost_vnd", sa.BigInteger, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "logged_by",
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
        sa.UniqueConstraint("rental_id", "log_date", name="uq_equipment_log_rental_date"),
        sa.CheckConstraint(
            "usage_state IN ('used', 'idle', 'maintenance', 'off')",
            name="ck_equipment_logs_state",
        ),
    )
    op.create_index(
        "ix_equipment_logs_rental_date",
        "equipment_rental_logs",
        ["rental_id", "log_date"],
    )

    op.create_table(
        "equipment_rental_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rental_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipment_rentals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Số hoá đơn NCC gửi (HD-2026-0042 hoặc 0089456 — text)
        sa.Column("invoice_number", sa.Text, nullable=False),
        # Period that this invoice covers
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        # What the NCC invoiced (their count of days billable)
        sa.Column("billable_days_claimed", sa.Integer, nullable=False),
        sa.Column("amount_vnd_claimed", sa.BigInteger, nullable=False),
        # What our site logs say (computed at acceptance time, stored
        # for audit so a later re-calc doesn't quietly rewrite history).
        sa.Column("billable_days_per_logs", sa.Integer, nullable=False),
        sa.Column("amount_vnd_per_logs", sa.BigInteger, nullable=False),
        sa.Column("variance_vnd", sa.BigInteger, nullable=False),
        # pending_review | accepted | disputed | paid
        sa.Column("status", sa.Text, nullable=False, server_default="pending_review"),
        sa.Column("dispute_note", sa.Text, nullable=True),
        sa.Column(
            "reconciled_by",
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
        sa.CheckConstraint(
            "status IN ('pending_review', 'accepted', 'disputed', 'paid')",
            name="ck_equipment_invoices_status",
        ),
        sa.UniqueConstraint(
            "rental_id", "invoice_number",
            name="uq_equipment_invoice_rental_number",
        ),
    )

    # ---- RLS on all three tables ----
    for table in (
        "equipment_rentals",
        "equipment_rental_logs",
        "equipment_rental_invoices",
    ):
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
    op.drop_table("equipment_rental_invoices")
    op.drop_table("equipment_rental_logs")
    op.drop_table("equipment_rentals")
