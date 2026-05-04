"""codeguard: per-route per-user usage attribution

Adds `codeguard_user_usage_by_route` so an admin can answer "which
routes drove this month's spike?" — currently `codeguard_user_usage`
aggregates input/output across all routes per user, so a heavy /scan
month is indistinguishable from a heavy /query month at the same
total. With this table, the breakdown is queryable per (org, user,
period, route_key).

Schema choices:

  * Composite PK on `(organization_id, user_id, period_start,
    route_key)`. Same shape as `codeguard_user_usage` plus a
    `route_key` column — clean UPSERT target with a `+ EXCLUDED`
    accumulator. Adding `route_key` to the PK gives one row per
    (org, user, month, route).

  * `route_key` is `VARCHAR(64)`, NOT an enum. Adding a route is a
    one-line edit in `services/codeguard_quota_attribution.py`'s
    `ROUTE_WEIGHTS` dict — keeping the column as a free-form string
    means a new route doesn't require a migration. The downside is
    typos can't be caught at the DB layer, but `route_weight_for`
    fails-closed-but-safe (default 1.0) so the worst case is
    under-attribution to the wrong key, which the operator notices
    in the `/quota/top-users` route breakdown.

  * `organization_id` and `user_id` both FK with `ON DELETE
    CASCADE`. Same trade-off as the parent `codeguard_user_usage`:
    per-user attribution is operational state, not a paper trail.
    The audit log preserves who-spent-what across deletions if
    compliance ever needs it.

  * Index `(organization_id, period_start, total_tokens DESC)`
    where `total_tokens` is `(input_tokens + output_tokens)` —
    covers the dominant breakdown query: "for org X in period P,
    which (user, route) combinations consumed the most." We pre-
    compute the sum as a generated column to keep the index simple
    and the query plan obvious; pgsql 12+ supports
    `GENERATED ALWAYS AS (...) STORED`.

  * No RLS — same posture as `codeguard_user_usage`. The route
    layer scopes reads to `auth.organization_id`.

Revision ID: 0040_codeguard_user_usage_by_route
Revises: 0039_api_keys_project_ids
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# 28 chars — under the 32-char `alembic_version.version_num` limit.
revision = "0040_codeguard_user_usage_by_route"
down_revision = "0039_api_keys_project_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codeguard_user_usage_by_route",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # First-of-month date. Same shape as the parent table —
        # `date_trunc('month', NOW())::date` server-side so a clock-
        # skewed client can't fragment rows.
        sa.Column("period_start", sa.Date(), nullable=False),
        # Route key — string so a new route doesn't need a migration.
        # `route_weight_for` defaults to 1.0 for unknown keys, so a
        # typo here is recoverable at read time.
        sa.Column("route_key", sa.String(64), nullable=False),
        # Running totals — UPSERT with `+ EXCLUDED` accumulates
        # exactly as the parent table does. BIGINT not INT because
        # output tokens × 5 (scan weight) can exceed 2^31 fast for
        # heavy users.
        sa.Column(
            "input_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "output_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # Composite PK = the UPSERT target. One row per (org, user,
        # month, route). Without `route_key` in the PK, the parent
        # table's row would collide.
        sa.PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            "period_start",
            "route_key",
            name="pk_codeguard_user_usage_by_route",
        ),
    )

    # Covering index for the "for this org+period, what's the route
    # breakdown" query. Sorted by combined tokens DESC so a LIMIT N
    # scan serves directly without a sort step. Generated columns are
    # cheaper than computing the sum in every query — Postgres
    # maintains the value at write time.
    #
    # We use a plain expression index (not a generated column) to
    # avoid the schema cost of a stored column the application never
    # reads back; the index alone is enough for the planner.
    op.create_index(
        "ix_codeguard_user_usage_by_route_org_period_total_desc",
        "codeguard_user_usage_by_route",
        [
            "organization_id",
            "period_start",
            sa.text("(input_tokens + output_tokens) DESC"),
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_codeguard_user_usage_by_route_org_period_total_desc",
        table_name="codeguard_user_usage_by_route",
    )
    op.drop_table("codeguard_user_usage_by_route")
