"""codeguard: add halfvec + HNSW index on regulation_chunks.embedding

Migration 0005 punted on an ANN index because pgvector's ivfflat/hnsw on
the `vector` type cap at 2000 dims, and our embeddings are 3072-dim
(OpenAI text-embedding-3-large). Without an index, dense retrieval is a
sequential scan — fine during dev on tens of chunks, catastrophic once a
real code library is ingested.

DRAWBRIDGE already solved this on `document_chunks` in 0007_drawbridge_hnsw;
we mirror that exact pattern here: generated `halfvec(3072)` column + HNSW
index with `halfvec_cosine_ops`. The pipeline's `_dense_search` switches
to `embedding_half <=> CAST(:vec AS halfvec)` to actually hit the index.

Revision ID: 0009_codeguard_hnsw
Revises: 0008_codeguard_rls
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op


revision = "0009_codeguard_hnsw"
down_revision = "0008_codeguard_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # halfvec shipped with pgvector 0.7.0 (Apr 2024). 0007_drawbridge_hnsw
    # already runs this — idempotent, but safe to call again here in case
    # codeguard is applied against a fresh DB without drawbridge.
    op.execute("ALTER EXTENSION vector UPDATE")

    op.execute(
        """
        ALTER TABLE regulation_chunks
        ADD COLUMN IF NOT EXISTS embedding_half halfvec(3072)
        GENERATED ALWAYS AS (embedding::halfvec(3072)) STORED
        """
    )

    # HNSW tuning: pgvector defaults (m=16, ef_construction=64) — same as
    # DRAWBRIDGE. Regulation corpora are much smaller than project docs
    # (order of 10k chunks even with every Vietnamese building code), so
    # defaults are comfortable. Revisit if recall or latency degrade.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_regulation_chunks_embedding_half_hnsw
        ON regulation_chunks
        USING hnsw (embedding_half halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_regulation_chunks_embedding_half_hnsw")
    op.execute("ALTER TABLE regulation_chunks DROP COLUMN IF EXISTS embedding_half")
