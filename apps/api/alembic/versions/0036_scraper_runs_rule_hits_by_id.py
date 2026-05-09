"""scraper_runs: per-rule-id hit counter

Adds `rule_hits_by_id` to `scraper_runs`. Pairs with the rules
admin shipped in batch B.2 + the existing `rule_hits` column (which
is keyed by `material_code`).

Why a sibling column rather than reshape `rule_hits`:

  * `rule_hits` is keyed by `material_code` and is the primary "did
    coverage shift?" signal — the schema is stable + already feeds
    the drift sparkline + email/Slack alerts.
  * `rule_hits_by_id` is keyed by `normalizer_rules.id` (UUID) and
    answers a different question: "did THIS rule fire?" The two
    questions don't merge cleanly because a single material_code
    can be emitted by multiple rules (one in-code + one DB
    override).
  * Keeping them sibling-shaped means readers that only care about
    one don't have to discriminate inside a polymorphic JSON.

Default `'{}'::jsonb` so existing rows + the next deploy's first
scrape (which writes the column) both round-trip without touching
historical telemetry.

No index. The expected access pattern is "load N most-recent
runs and aggregate in app code" — same as `rule_hits` — which the
existing `(slug, started_at DESC)` index already covers.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_scraper_runs_rule_hits_by_id"
down_revision = "0035_codeguard_user_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scraper_runs",
        sa.Column(
            "rule_hits_by_id",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("scraper_runs", "rule_hits_by_id")
