"""codeguard: per-org token quota + monthly usage tracking

Builds on the cost telemetry that landed earlier — tokens are now
captured per-call via `_record_llm_call` + `_UsageCaptureHandler`, but
nothing stops a runaway script from spending an org through their
budget. This migration adds two narrow tables that turn telemetry into
enforcement:

  * `codeguard_org_quotas` — opt-in monthly quota per org. Missing row =
    unlimited (matches the "telemetry-then-enforce" rollout: orgs aren't
    capped retroactively, only those explicitly assigned a limit).
  * `codeguard_org_usage` — running per-month token totals. Incremented
    after each successful LLM call by the route layer's quota dependency.
    Composite PK `(org_id, period_start)` so the same org/month UPSERTs
    cleanly.

Why two tables not one: `org_quotas` is a configuration row that ops
edits manually (or via a future admin UI); `org_usage` is high-write
counters touched on every request. Splitting them lets the quota row
stay stable + cacheable while usage churns.

Why not a column on `organizations`: keeps codeguard's enforcement
logic isolated. A future module that wants its own quotas (e.g.
DRAWBRIDGE LLM costs) can add `drawbridge_org_quotas` without colliding.

RLS is intentionally NOT enabled on either table — both are managed
by the route layer (codeguard pipeline) using the superuser session,
not by user-facing queries. The `org_id` column is the access-control
key but enforcement happens in application code, not Postgres policy.

Revision ID: 0023_codeguard_quotas
Revises: 0022_audit_events
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_codeguard_quotas"
down_revision = "0022_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codeguard_org_quotas",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # NULL = unlimited on that dimension. Most orgs will get a single
        # combined budget by setting both to the same value × some ratio,
        # but keeping them independent lets ops tune for the asymmetric
        # cost of input vs output tokens (Anthropic prices output ~5×
        # input, so an org pinned by output_tokens is the common case).
        sa.Column("monthly_input_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("monthly_output_token_limit", sa.BigInteger(), nullable=True),
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
    )

    op.create_table(
        "codeguard_org_usage",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # First day of the calendar month this usage row covers. Using
        # DATE rather than a TIMESTAMP is deliberate: clock skew + TZ
        # shifts shouldn't move a single LLM call between two billing
        # periods. Server-side `date_trunc('month', NOW())::date` is the
        # canonical way to compute this.
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column(
            "input_tokens", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "output_tokens", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("organization_id", "period_start"),
    )
    # Index for the common ops query: "show me current-month usage
    # across all orgs sorted by total." Without it, that scan is a
    # full-table read every dashboard refresh.
    op.create_index(
        "ix_codeguard_org_usage_period_start",
        "codeguard_org_usage",
        ["period_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_codeguard_org_usage_period_start", table_name="codeguard_org_usage")
    op.drop_table("codeguard_org_usage")
    op.drop_table("codeguard_org_quotas")
