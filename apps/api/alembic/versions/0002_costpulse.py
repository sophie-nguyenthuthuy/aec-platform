"""costpulse tables: material_prices, estimates, boq_items, suppliers, rfqs

Revision ID: 0002_costpulse
Revises: 0001_core
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_costpulse"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("categories", postgresql.ARRAY(sa.Text), server_default=sa.text("ARRAY[]::text[]")),
        sa.Column("provinces", postgresql.ARRAY(sa.Text), server_default=sa.text("ARRAY[]::text[]")),
        sa.Column("contact", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("rating", sa.Numeric),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_suppliers_org", "suppliers", ["organization_id"])
    op.create_index("ix_suppliers_categories", "suppliers", ["categories"], postgresql_using="gin")
    op.create_index("ix_suppliers_provinces", "suppliers", ["provinces"], postgresql_using="gin")

    op.create_table(
        "material_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("material_code", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("unit", sa.Text, nullable=False),
        sa.Column("price_vnd", sa.Numeric, nullable=False),
        sa.Column("price_usd", sa.Numeric),
        sa.Column("province", sa.Text),
        sa.Column("source", sa.Text),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("expires_date", sa.Date),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="SET NULL")),
        sa.UniqueConstraint("material_code", "province", "effective_date", name="uq_material_prices_code_province_date"),
    )
    op.create_index("ix_material_prices_code", "material_prices", ["material_code"])
    op.create_index("ix_material_prices_category", "material_prices", ["category"])
    op.create_index("ix_material_prices_province", "material_prices", ["province"])
    op.create_index("ix_material_prices_effective", "material_prices", ["effective_date"])

    op.create_table(
        "estimates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("total_vnd", sa.BigInteger),
        sa.Column("confidence", sa.Text),
        sa.Column("method", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_estimates_org_project", "estimates", ["organization_id", "project_id"])
    op.create_index("ix_estimates_status", "estimates", ["organization_id", "status"])

    op.create_table(
        "boq_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("estimate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("boq_items.id", ondelete="CASCADE")),
        sa.Column("sort_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("code", sa.Text),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("unit", sa.Text),
        sa.Column("quantity", sa.Numeric),
        sa.Column("unit_price_vnd", sa.Numeric),
        sa.Column("total_price_vnd", sa.Numeric),
        sa.Column("material_code", sa.Text),
        sa.Column("source", sa.Text),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_boq_items_estimate", "boq_items", ["estimate_id", "sort_order"])
    op.create_index("ix_boq_items_parent", "boq_items", ["parent_id"])

    op.create_table(
        "rfqs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("estimate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("estimates.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("sent_to", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default=sa.text("ARRAY[]::uuid[]")),
        sa.Column("responses", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("deadline", sa.Date),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_rfqs_org_project", "rfqs", ["organization_id", "project_id"])
    op.create_index("ix_rfqs_status", "rfqs", ["organization_id", "status"])

    op.create_table(
        "price_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_code", sa.Text, nullable=False),
        sa.Column("province", sa.Text),
        sa.Column("threshold_pct", sa.Numeric, server_default=sa.text("5")),
        sa.Column("last_price_vnd", sa.Numeric),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("organization_id", "user_id", "material_code", "province", name="uq_price_alerts_unique"),
    )
    op.create_index("ix_price_alerts_material", "price_alerts", ["material_code"])

    for table in ("estimates", "boq_items", "rfqs", "price_alerts"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY tenant_isolation_estimates ON estimates "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_boq_items ON boq_items "
        "USING (EXISTS (SELECT 1 FROM estimates e WHERE e.id = boq_items.estimate_id "
        "AND e.organization_id = current_setting('app.current_org_id', true)::uuid))"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_rfqs ON rfqs "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_price_alerts ON price_alerts "
        "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
    )

    # suppliers: platform-wide rows (org_id NULL) visible to all; org-scoped rows isolated.
    op.execute("ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_visibility_suppliers ON suppliers "
        "USING (organization_id IS NULL "
        "OR organization_id = current_setting('app.current_org_id', true)::uuid)"
    )


def downgrade() -> None:
    for table in ("price_alerts", "rfqs", "boq_items", "estimates", "material_prices", "suppliers"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
