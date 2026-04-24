"""codeguard tables

Revision ID: 0005_codeguard
Revises: 0004_bidradar
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_codeguard"
down_revision = "0004_bidradar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "regulations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("country_code", sa.CHAR(length=2), nullable=False),
        sa.Column("jurisdiction", sa.Text()),
        sa.Column("code_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text()),
        sa.Column("effective_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("source_url", sa.Text()),
        sa.Column("content", postgresql.JSONB()),
        sa.Column("raw_text", sa.Text()),
        sa.Column("language", sa.Text(), server_default="vi"),
    )
    op.create_index("ix_regulations_country_category", "regulations", ["country_code", "category"])
    op.create_index("ix_regulations_code_name", "regulations", ["code_name"])

    op.execute("""
        CREATE TABLE regulation_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            regulation_id UUID REFERENCES regulations(id) ON DELETE CASCADE,
            section_ref TEXT,
            content TEXT NOT NULL,
            embedding vector(3072)
        )
    """)
    # pgvector ANN indexes on the `vector` type cap at 2000 dims; embedding
    # is 3072. The ANN index is added separately in 0009_codeguard_hnsw
    # via a generated halfvec column + HNSW (supports up to 4000 dims).
    op.create_index("ix_regulation_chunks_regulation", "regulation_chunks", ["regulation_id"])

    op.create_table(
        "compliance_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
        ),
        sa.Column("check_type", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("input", postgresql.JSONB()),
        sa.Column("findings", postgresql.JSONB()),
        sa.Column("regulations_referenced", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_compliance_checks_project", "compliance_checks", ["project_id"])
    op.create_index("ix_compliance_checks_org", "compliance_checks", ["organization_id"])

    op.create_table(
        "permit_checklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
        ),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("project_type", sa.Text(), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_permit_checklists_project", "permit_checklists", ["project_id"])


def downgrade() -> None:
    op.drop_table("permit_checklists")
    op.drop_table("compliance_checks")
    op.drop_table("regulation_chunks")
    op.drop_table("regulations")
