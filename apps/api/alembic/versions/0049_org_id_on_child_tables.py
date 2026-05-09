"""organization_id + RLS on assistant_messages, audit_pins, boq_items

Three child tables previously relied on parent-table RLS for tenant
isolation: `assistant_messages` via `assistant_threads`, `audit_pins`
via `audit_events`, `boq_items` via `estimates`. The parent FK
CASCADE keeps lifecycle clean, but RLS-via-parent leaves the child
table itself unprotected — any code path that queries the child
without going through the parent (raw SQL, future denormalised
indexes, etc.) bypasses tenant isolation.

`test_orm_tables_organization_id_audit.py` flagged all three as
tenant-bearing-without-`organization_id`. Defence-in-depth fix:
each child gets its own `organization_id` column, backfilled from
the parent, plus the canonical RLS policy from the convention used
across every other tenant-bearing table.

Per-table backfill source:

  * `assistant_messages.organization_id` <- `assistant_threads.organization_id`
    via `thread_id` FK.
  * `audit_pins.organization_id` <- `audit_events.organization_id`
    via `audit_event_id` FK.
  * `boq_items.organization_id` <- `estimates.organization_id`
    via `estimate_id` FK.

Each child's parent FK is CASCADE today, so this column will track
the parent for the row's whole lifetime — no later
update-on-parent-change needed.

Migration shape (per table):

  1. ADD COLUMN organization_id uuid (nullable; matches existing rows).
  2. Backfill from parent.
  3. SET NOT NULL.
  4. ADD FOREIGN KEY ... ON DELETE CASCADE.
  5. ENABLE ROW LEVEL SECURITY.
  6. CREATE POLICY tenant_isolation_<table> with USING + WITH CHECK
     (per `0021_rls_with_check_everywhere` convention).

Revision ID: 0049_org_id_on_child_tables
Revises: 0048_retention_overrides_rls
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0049_org_id_on_child_tables"
down_revision = "0048_retention_overrides_rls"
branch_labels = None
depends_on = None


# (child_table, parent_table, fk_column_on_child) — drives both upgrade
# and downgrade. Order matters only for readability; the operations are
# independent across rows.
_CHILDREN = (
    ("assistant_messages", "assistant_threads", "thread_id"),
    ("audit_pins", "audit_events", "audit_event_id"),
    ("boq_items", "estimates", "estimate_id"),
)


def upgrade() -> None:
    for child, parent, fk_col in _CHILDREN:
        op.add_column(
            child,
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.execute(
            f"UPDATE {child} SET organization_id = parent.organization_id "
            f"FROM {parent} AS parent WHERE {child}.{fk_col} = parent.id"
        )
        op.alter_column(child, "organization_id", nullable=False)
        op.create_foreign_key(
            f"fk_{child}_organization_id",
            child,
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.execute(f"ALTER TABLE {child} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{child} ON {child} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid) "
            "WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for child, _parent, _fk_col in _CHILDREN:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{child} ON {child}")
        op.execute(f"ALTER TABLE {child} DISABLE ROW LEVEL SECURITY")
        op.drop_constraint(f"fk_{child}_organization_id", child, type_="foreignkey")
        op.drop_column(child, "organization_id")
