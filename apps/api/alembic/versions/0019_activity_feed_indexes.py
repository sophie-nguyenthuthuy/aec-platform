"""activity-feed performance indexes — covering (organization_id, <timestamp>)

The activity feed (`/api/v1/activity`) and the daily digest cron both
fire a UNION-ALL across six source tables, each branch shaped:

    SELECT ... FROM <table>
    WHERE organization_id = :org_id
      AND <timestamp_col> >= :since
    ORDER BY <timestamp_col> DESC

The existing indexes cover `(organization_id, project_id)` for tenant
filters but miss the time component — every branch falls back to a
full scan + sort once we have any volume. Postgres won't combine the
org index with a timestamp filter efficiently.

Each composite below lets the planner do an index range scan that
filters on org AND orders by time without a Sort node. Two of them are
**partial** because the column is NULL for the dominant share of rows
(a task is rarely completed, a handover package is rarely delivered);
partial indexes stay small and the planner uses them for the
`IS NOT NULL` predicate the activity feed already carries.

Revision ID: 0019_activity_feed_indexes
Revises: 0018_invitations_rls_with_check
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op


revision = "0019_activity_feed_indexes"
down_revision = "0018_invitations_rls_with_check"
branch_labels = None
depends_on = None


# (table, index_name, column, partial_clause | None)
# `column` is the timestamp; the index is `(organization_id, <column> DESC)`.
# `partial_clause` is None for full indexes or "<column> IS NOT NULL" for
# the columns that are predominantly NULL.
INDEXES: list[tuple[str, str, str, str | None]] = [
    ("change_orders", "ix_change_orders_org_created", "created_at", None),
    ("tasks", "ix_tasks_org_completed", "completed_at", "completed_at IS NOT NULL"),
    ("safety_incidents", "ix_safety_incidents_org_detected", "detected_at", None),
    ("defects", "ix_defects_org_reported", "reported_at", None),
    ("rfis", "ix_rfis_org_created", "created_at", None),
    (
        "handover_packages",
        "ix_handover_packages_org_delivered",
        "delivered_at",
        "delivered_at IS NOT NULL",
    ),
]


def upgrade() -> None:
    for table, name, col, partial in INDEXES:
        # CREATE INDEX (without CONCURRENTLY) — Alembic runs migrations
        # inside a transaction by default, and CONCURRENTLY can't run in
        # one. For a 50-customer rollout these tables are small enough
        # that the brief lock is fine; revisit when we cross 100k rows.
        clause = f"WHERE {partial}" if partial else ""
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"(organization_id, {col} DESC) {clause}"
        )


def downgrade() -> None:
    for _table, name, _col, _partial in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
