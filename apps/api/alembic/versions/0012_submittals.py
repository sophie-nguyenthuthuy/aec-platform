"""submittals + RFI AI tables

Tables created:
  * submittals
  * submittal_revisions
  * rfi_embeddings (vector(3072) — managed in raw SQL)
  * rfi_response_drafts

The vector column on rfi_embeddings reuses the same pgvector setup as
document_chunks.embedding (created in 0007_drawbridge_hnsw). The HNSW
index here uses cosine ops because RFIs are short, freeform text.

Revision ID: 0012_submittals
Revises: 0011_schedulepilot
Create Date: 2026-04-26
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0012_submittals"
down_revision = "0011_schedulepilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- submittals ----
    op.create_table(
        "submittals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
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
            nullable=False,
        ),
        sa.Column("package_number", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "submittal_type", sa.Text(), nullable=False, server_default="shop_drawing"
        ),
        sa.Column("spec_section", sa.Text()),
        sa.Column("csi_division", sa.Text()),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="pending_review"
        ),
        sa.Column(
            "current_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "ball_in_court", sa.Text(), nullable=False, server_default="designer"
        ),
        sa.Column(
            "contractor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("due_date", sa.Date()),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "project_id", "package_number", name="uq_submittals_project_number"
        ),
    )
    op.create_index(
        "ix_submittals_project", "submittals", ["organization_id", "project_id"]
    )
    op.create_index(
        "ix_submittals_status", "submittals", ["organization_id", "status"]
    )
    op.create_index(
        "ix_submittals_ball_in_court",
        "submittals",
        ["project_id", "ball_in_court"],
    )

    # ---- submittal_revisions ----
    op.create_table(
        "submittal_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submittal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("submittals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("reviewer_notes", sa.Text()),
        sa.Column(
            "annotations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "submittal_id",
            "revision_number",
            name="uq_submittal_revisions_per_submittal",
        ),
    )
    op.create_index(
        "ix_submittal_revisions_submittal",
        "submittal_revisions",
        ["submittal_id", "revision_number"],
    )

    # ---- rfi_embeddings (vector(3072) added separately in raw SQL) ----
    op.create_table(
        "rfi_embeddings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rfi_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfis.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    # The vector column itself + HNSW cosine index — pgvector is already
    # installed via the drawbridge HNSW migration. pgvector caps `vector`
    # HNSW indexes at 2000 dims, so mirror 0007_drawbridge_hnsw: store the
    # 3072-d vector and add a `halfvec(3072)` generated column for the
    # ANN index. Retrieval SQL casts the query vector with `::halfvec`.
    op.execute("ALTER TABLE rfi_embeddings ADD COLUMN embedding vector(3072)")
    op.execute(
        """
        ALTER TABLE rfi_embeddings
        ADD COLUMN embedding_half halfvec(3072)
        GENERATED ALWAYS AS (embedding::halfvec(3072)) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_rfi_embeddings_hnsw ON rfi_embeddings "
        "USING hnsw (embedding_half halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.create_index(
        "ix_rfi_embeddings_org", "rfi_embeddings", ["organization_id"]
    )

    # ---- rfi_response_drafts ----
    op.create_table(
        "rfi_response_drafts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rfi_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rfis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "accepted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
    )
    op.create_index(
        "ix_rfi_response_drafts_rfi",
        "rfi_response_drafts",
        ["rfi_id", "generated_at"],
    )

    # ---- RLS ----
    for table in (
        "submittals",
        "submittal_revisions",
        "rfi_embeddings",
        "rfi_response_drafts",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in (
        "rfi_response_drafts",
        "rfi_embeddings",
        "submittal_revisions",
        "submittals",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
