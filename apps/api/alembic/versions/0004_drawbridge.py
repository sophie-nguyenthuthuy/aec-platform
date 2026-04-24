"""drawbridge tables: document_sets, documents, document_chunks, conflicts, rfis

Revision ID: 0004_drawbridge
Revises: 0003_siteeye
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_drawbridge"
down_revision = "0003_siteeye"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension is already provisioned in 0001_core; ensure idempotently.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "document_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("discipline", sa.Text()),
        sa.Column("revision", sa.Text()),
        sa.Column("issued_date", sa.Date()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_document_sets_org_project", "document_sets", ["organization_id", "project_id"])
    op.create_index("ix_document_sets_discipline", "document_sets", ["discipline"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("document_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_sets.id", ondelete="SET NULL")),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("doc_type", sa.Text()),
        sa.Column("drawing_number", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("revision", sa.Text()),
        sa.Column("discipline", sa.Text()),
        sa.Column("scale", sa.Text()),
        sa.Column("processing_status", sa.Text(), server_default="pending"),
        sa.Column("extracted_data", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("thumbnail_url", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_documents_org_project", "documents", ["organization_id", "project_id"])
    op.create_index("ix_documents_set", "documents", ["document_set_id"])
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"])
    op.create_index("ix_documents_discipline", "documents", ["discipline"])
    op.create_index("ix_documents_drawing_number", "documents", ["drawing_number"])
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])

    # document_chunks has a vector(3072) column — create via raw SQL for pgvector support.
    op.execute(
        """
        CREATE TABLE document_chunks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
          page_number INTEGER,
          chunk_type TEXT,
          content TEXT,
          bbox JSONB,
          embedding vector(3072)
        )
        """
    )
    op.create_index("ix_document_chunks_document", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_org_project", "document_chunks", ["organization_id", "project_id"])
    op.create_index("ix_document_chunks_page", "document_chunks", ["document_id", "page_number"])
    op.create_index("ix_document_chunks_type", "document_chunks", ["chunk_type"])
    # pgvector ANN indexes cap at 2000 dims; embedding is 3072. Index deferred.
    # TODO: halfvec(3072) + hnsw, or reduce embedding dims, then add index.

    op.create_table(
        "conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("severity", sa.Text()),
        sa.Column("conflict_type", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("document_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("chunk_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_chunks.id", ondelete="SET NULL")),
        sa.Column("document_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("chunk_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_chunks.id", ondelete="SET NULL")),
        sa.Column("ai_explanation", sa.Text()),
        sa.Column("resolution_notes", sa.Text()),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index("ix_conflicts_org_project", "conflicts", ["organization_id", "project_id"])
    op.create_index("ix_conflicts_status", "conflicts", ["status"])
    op.create_index("ix_conflicts_severity", "conflicts", ["severity"])
    op.create_index("ix_conflicts_detected", "conflicts", ["detected_at"])

    op.create_table(
        "rfis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("number", sa.Text()),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("priority", sa.Text(), server_default="normal"),
        sa.Column("related_document_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("raised_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_date", sa.Date()),
        sa.Column("response", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "number", name="uq_rfis_project_number"),
    )
    op.create_index("ix_rfis_org_project", "rfis", ["organization_id", "project_id"])
    op.create_index("ix_rfis_status", "rfis", ["status"])
    op.create_index("ix_rfis_assigned", "rfis", ["assigned_to"])
    op.create_index("ix_rfis_due_date", "rfis", ["due_date"])

    # Row-level security — tenant isolation (mirrors pattern in 0001_core / 0003_siteeye).
    for table in ("document_sets", "documents", "document_chunks", "conflicts", "rfis"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("rfis", "conflicts", "document_chunks", "documents", "document_sets"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
