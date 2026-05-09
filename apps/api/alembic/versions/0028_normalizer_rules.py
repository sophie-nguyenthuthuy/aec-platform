"""normalizer_rules — DB-backed regex rules for the price scraper

Today `services.price_scrapers.normalizer._RULES` is a list of regex
tuples in code. Tuning a rule (or adding one for a province whose
`unmatched_sample` has shown up in the drift telemetry) means a
deploy. This migration adds a table that ops can edit live; the
normaliser merges DB rules on top of code rules at runtime.

Schema rationale:

  * **Global, no organization_id, no RLS.** Material codes are
    platform-wide; if one tenant adds a rule, every tenant benefits.
    Persisted via `AdminSessionFactory`. Matches the `scraper_runs`
    posture from migration 0012.
  * `priority` orders rules — lower fires first. Code rules effectively
    have priority=∞ (last resort) so a DB rule can override them.
  * `material_code` is what the rule emits when the regex matches.
    Free string rather than an FK because the catalogue list lives in
    `_RULES` (canonical) and could grow without a migration.
  * `enabled` is a soft delete — disabling a noisy rule is a one-
    column write, no DELETE that would break audit history.
  * `(pattern, flags)` is intentionally NOT unique. Two rules with
    the same pattern but different `material_code` is a valid (if
    unusual) shape — e.g. "thép" → REBAR_CB300 OR REBAR_CB500
    depending on which province's bulletin tags it.

Revision ID: 0028_normalizer_rules
Revises: 0027_search_queries
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0028_normalizer_rules"
down_revision = "0027_search_queries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "normalizer_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Lower = higher priority. DB rules at low priority override
        # the code rules; rarely-used DB additions can land at high
        # priority so they don't shadow the canonical regexes.
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("material_code", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("canonical_name", sa.Text, nullable=False),
        # Comma-separated unit hints (e.g. "kg,tấn,ton") — matches the
        # `preferred_units` tuple in `_Rule`. Normaliser splits on
        # comma + strip on read.
        sa.Column("preferred_units", sa.Text, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )
    # Hot-path index: normaliser does `SELECT * WHERE enabled=true
    # ORDER BY priority` on every cron run.
    op.create_index(
        "ix_normalizer_rules_enabled_priority",
        "normalizer_rules",
        ["enabled", "priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_normalizer_rules_enabled_priority", table_name="normalizer_rules")
    op.drop_table("normalizer_rules")
