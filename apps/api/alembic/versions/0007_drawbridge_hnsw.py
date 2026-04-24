"""drawbridge: add halfvec + HNSW index on document_chunks.embedding

pgvector caps `vector` ivfflat/hnsw ANN indexes at 2000 dims. Our embeddings
are 3072-dim (OpenAI text-embedding-3-large). halfvec supports HNSW up to
4000 dims and halves storage — adequate for cosine retrieval quality.

Strategy:
  1. Add `embedding_half halfvec(3072)` as a generated column from `embedding`.
  2. Build a HNSW index on `embedding_half` using halfvec_cosine_ops.
  3. Query path continues to write `embedding vector(3072)`; retrieval SQL
     can switch to `embedding_half <=> CAST(:vec AS halfvec)` to hit the index,
     or keep the existing `embedding <=> CAST(:vec AS vector)` for exact scan.

Revision ID: 0007_drawbridge_hnsw
Revises: 0006_merge_heads
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op


revision = "0007_drawbridge_hnsw"
down_revision = "0006_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # halfvec shipped with pgvector 0.7.0 (Apr 2024). CREATE EXTENSION from 0001
    # must have been at >= 0.7.0 for this to apply. If running against an older
    # pgvector, upgrade the extension first: ALTER EXTENSION vector UPDATE;
    op.execute("ALTER EXTENSION vector UPDATE")

    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS embedding_half halfvec(3072)
        GENERATED ALWAYS AS (embedding::halfvec(3072)) STORED
        """
    )

    # HNSW tuning: m=16 / ef_construction=64 are pgvector defaults and fit
    # our corpus profile (tens of thousands of chunks per org). Revisit if
    # recall or latency degrade past 500k chunks.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_half_hnsw
        ON document_chunks
        USING hnsw (embedding_half halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_half_hnsw")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding_half")
