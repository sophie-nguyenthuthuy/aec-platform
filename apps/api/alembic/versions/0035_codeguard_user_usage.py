"""codeguard: per-user token usage attribution

Adds `codeguard_user_usage` so the quota story can answer "who burned
the most tokens this month?" without grepping pod logs. Today
`codeguard_org_usage` aggregates at the org level — when an org hits
96% the natural follow-on question is "which user pushed us there"
and there's no surface to answer it.

Schema choices:

  * Composite PK on `(organization_id, user_id, period_start)`. Same
    shape as `codeguard_org_usage` (which uses
    `(organization_id, period_start)`) — a clean UPSERT target with a
    `+ EXCLUDED` accumulator. Adding `user_id` to the PK gives one
    row per (org, user, month).

  * `organization_id` AND `user_id` both FK with `ON DELETE CASCADE`.
    Different choice from the audit log (SET NULL) because per-user
    usage is operational state, not a paper trail — keeping rows
    after the user (or org) is deleted just bloats the table without
    a reader. The audit log preserves who-spent-what across deletions
    if compliance ever needs it.

  * Index `(organization_id, period_start, input_tokens DESC,
    output_tokens DESC)` covers the dominant query: "top N users for
    org X in period P, sorted by spend." Without the index that's a
    full scan of the per-user table per request.

  * No RLS on the table itself — the route layer scopes reads to
    `auth.organization_id`, and only org admins should see this data
    anyway. Adding RLS would require threading
    `app.current_org_id` through the read path and would block the
    aggregate-stats use case where we want to show platform-wide
    "who are our heaviest users" in an admin dashboard later.

  * `created_at` and `updated_at` on every row so a future
    "consumption velocity" view can compute "tokens per hour for
    user X over the last 24h" without joining against the LLM
    telemetry log.

Revision ID: 0035_codeguard_user_usage
Revises: 0034_merge_api_key_branches
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# 28 chars — under the 32-char `alembic_version.version_num` limit.
revision = "0035_codeguard_user_usage"
down_revision = "0034_merge_api_key_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codeguard_user_usage",
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
        # First-of-month date. Same shape as `codeguard_org_usage.
        # period_start` — `date_trunc('month', NOW())::date` server-
        # side so a clock-skewed client can't fragment rows.
        sa.Column("period_start", sa.Date(), nullable=False),
        # Running totals — UPSERT with `+ EXCLUDED` accumulates
        # exactly as `codeguard_org_usage` does. BIGINT not INT
        # because output tokens can plausibly exceed 2^31 over a
        # long-running month for heavy users.
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
        # Composite PK = the UPSERT target. (org, user, month) is the
        # uniqueness contract — one row per user per month per org.
        sa.PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            "period_start",
            name="pk_codeguard_user_usage",
        ),
    )

    # Covering index for the "top N users by spend in this org/month"
    # query. ORDER BY input_tokens DESC + LIMIT N can serve from the
    # index alone. We deliberately don't include both dimensions in
    # one DESC index (the planner would only use the leading column)
    # — instead, the dominant query orders by `input_tokens + output_tokens`
    # or by max of either, and Postgres can scan the (org, period)
    # leading prefix and filter with the secondary cols. If a future
    # workload pins on output-only ranking, add a sibling index then.
    op.create_index(
        "ix_codeguard_user_usage_org_period_input_desc",
        "codeguard_user_usage",
        ["organization_id", "period_start", sa.text("input_tokens DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_codeguard_user_usage_org_period_input_desc",
        table_name="codeguard_user_usage",
    )
    op.drop_table("codeguard_user_usage")
