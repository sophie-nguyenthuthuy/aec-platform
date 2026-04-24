"""bidradar tables

Revision ID: 0004_bidradar
Revises: 0003_siteeye
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_bidradar"
down_revision = "0003_siteeye"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text()),
        sa.Column("type", sa.Text()),
        sa.Column("budget_vnd", sa.BigInteger()),
        sa.Column("currency", sa.Text(), server_default="VND"),
        sa.Column("country_code", sa.CHAR(length=2), server_default="VN"),
        sa.Column("province", sa.Text()),
        sa.Column("disciplines", postgresql.ARRAY(sa.Text())),
        sa.Column("project_types", postgresql.ARRAY(sa.Text())),
        sa.Column("submission_deadline", sa.TIMESTAMP(timezone=True)),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("description", sa.Text()),
        sa.Column("raw_url", sa.Text()),
        sa.Column("raw_payload", postgresql.JSONB()),
        sa.Column("scraped_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source", "external_id", name="uq_tenders_source_external"),
    )
    op.create_index("ix_tenders_deadline", "tenders", ["submission_deadline"])
    op.create_index("ix_tenders_country_province", "tenders", ["country_code", "province"])
    op.create_index("ix_tenders_disciplines", "tenders", ["disciplines"], postgresql_using="gin")

    op.create_table(
        "firm_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("disciplines", postgresql.ARRAY(sa.Text())),
        sa.Column("project_types", postgresql.ARRAY(sa.Text())),
        sa.Column("provinces", postgresql.ARRAY(sa.Text())),
        sa.Column("min_budget_vnd", sa.BigInteger()),
        sa.Column("max_budget_vnd", sa.BigInteger()),
        sa.Column("team_size", sa.Integer()),
        sa.Column("active_capacity_pct", sa.Numeric()),
        sa.Column("past_wins", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "tender_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_score", sa.Numeric()),
        sa.Column("estimated_value_vnd", sa.BigInteger()),
        sa.Column("competition_level", sa.Text()),
        sa.Column("win_probability", sa.Numeric()),
        sa.Column("recommended_bid", sa.Boolean()),
        sa.Column("ai_recommendation", postgresql.JSONB()),
        sa.Column("status", sa.Text(), server_default="new"),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("organization_id", "tender_id", name="uq_tender_matches_org_tender"),
    )
    op.create_index("ix_tender_matches_org_status", "tender_matches", ["organization_id", "status"])
    op.create_index(
        "ix_tender_matches_score",
        "tender_matches",
        ["organization_id", sa.text("match_score DESC")],
    )

    op.create_table(
        "tender_digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("top_match_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("sent_to", postgresql.ARRAY(sa.Text())),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("organization_id", "week_start", name="uq_tender_digests_org_week"),
    )

    for table in ("firm_profiles", "tender_matches", "tender_digests"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("tender_digests", "tender_matches", "firm_profiles", "tenders"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
