"""scraper_runs telemetry table for normaliser drift monitoring

Each invocation of `services.price_scrapers.run_scraper` writes one row
here. Together they form the time-series we use to detect drift —
provincial bulletins quietly renaming materials, our regex rules going
stale, or a province silently switching from monthly to quarterly
publication.

Schema rationale:
  * No `organization_id` and no RLS. Scraper telemetry is global ops
    data; tenants never read this. Persisted via `AdminSessionFactory`
    which connects as the BYPASSRLS `aec` role.
  * `unmatched_sample` is bounded (`run_scraper` caps at 25) and keeps
    distinct names only — large enough to spot patterns, small enough
    that 100k runs don't bloat the table.
  * `rule_hits` is a `{material_code: count}` map. Codes that hit zero
    are still listed so trend queries can spot a previously-active rule
    going to zero (the strongest drift signal).
  * `(slug, started_at desc)` index supports "give me the last N runs
    for province X" — the typical ops query.

Revision ID: 0012_scraper_runs
Revises: 0011_schedulepilot
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0012_scraper_runs"
down_revision = "0011_schedulepilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scraper_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("scraped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unmatched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("written", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "rule_hits",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "unmatched_sample",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_scraper_runs_slug_started_at",
        "scraper_runs",
        ["slug", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_scraper_runs_slug_started_at", table_name="scraper_runs")
    op.drop_table("scraper_runs")
