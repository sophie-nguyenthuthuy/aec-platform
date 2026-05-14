"""LLM spend events — per-call cost tracking for the org dashboard.

One row per LLM invocation across every module (codeguard, drawbridge,
winwork, bidradar, pulse weekly reports). Denormalised: each row
carries `cost_vnd` so the dashboard can sum without re-running the
pricing math on every aggregation.

Why a fresh table when codeguard_org_usage already counts tokens:
  * codeguard_org_usage is monthly-aggregate scoped to the codeguard
    module only. The L4-6 dashboard needs per-module breakdown
    ("Drawbridge consumed 45% of your AI spend this month").
  * Aggregating by org × module × provider × period from the wider
    table also lets us pivot by `provider` (Gemini cheap, Claude
    expensive) so customers can decide whether to swap models.

Retention: the existing retention worker prunes
`retention_policies`-marked tables; we register `llm_spend_events`
there separately if/when it needs eviction (currently keep forever
for billing audit).

Revision ID: 0051_llm_spend
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_llm_spend"
down_revision: Union[str, None] = "0050_billing"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "llm_spend_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # codeguard | drawbridge | winwork | bidradar | pulse | costpulse | siteeye | other
        sa.Column("module", sa.Text, nullable=False),
        # gemini | anthropic | openai
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        # Cached cost so dashboard SUMs don't re-evaluate pricing math
        # against the per-model rate table on every aggregation pass.
        sa.Column("cost_vnd", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("request_id", sa.Text, nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_llm_spend_org_occurred",
        "llm_spend_events",
        ["organization_id", "occurred_at"],
    )
    op.create_index(
        "ix_llm_spend_org_module",
        "llm_spend_events",
        ["organization_id", "module"],
    )


def downgrade() -> None:
    op.drop_table("llm_spend_events")
