"""Resize every pgvector column from 3072 → 768 dim for Gemini embeddings.

The original embedding pipeline used OpenAI's `text-embedding-3-large`
(3072 dim). The free-tier deploy pivots to Google Gemini's
`text-embedding-004` (768 dim). pgvector columns are typed by
dimensionality at create time — you cannot widen or narrow them in
place, and a stored 3072-d vector can't be coerced into a 768-d
column. So this migration:

  1. Drops every `embedding vector(3072)` column across the four
     tables that have one (and the associated HNSW indexes that
     reference them).
  2. Recreates each column as `vector(768)`.
  3. Re-creates HNSW indexes with `vector_cosine_ops` against the
     new column.

Existing embedding rows are NOT migrated — there is no transform from
3072-d OpenAI vectors to 768-d Gemini vectors. After this migration,
the embedding tables are empty in terms of vectors (but the metadata
rows, FKs, etc. stay). Re-run the seed (`make seed-demo` or
`make seed-codeguard-all`) to repopulate.

Tables touched (cross-reference with `grep -rn vector\\(3072\\) apps/api/alembic`):

  * `chunks`              (created in 0001_core)         — CodeGuard chunks
  * `document_chunks`     (created in 0004_drawbridge)   — Drawbridge
  * `codeguard_doc_chunks`(created in 0005_codeguard)    — CodeGuard ingest
  * `rfi_embeddings`      (created in 0012_submittals)   — RFI similarity

The pre-existing dim-3072 HNSW indexes live in:

  * 0001_core: `ix_chunks_embedding_hnsw`           (chunks)
  * 0007_drawbridge_hnsw: `ix_document_chunks_embedding_hnsw`
  * 0009_codeguard_hnsw: `ix_codeguard_doc_chunks_embedding_hnsw`
  * 0012_submittals: (no HNSW; smaller table, falls back to seq scan)

Down-migration restores 3072-d columns and indexes for symmetry, but
again, embedding rows aren't preserved across either direction.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0041_gemini_embedding_dim"
# Stack on top of the existing post-merge head. See `alembic heads` —
# 0040 is the final route-attribution table, the prefs/webhooks merge
# (`ceff072b3343_merge_prefs_webhooks_heads`) sits beneath the 0033
# audit-actor migration. 0040 is the single tail.
down_revision = "0040_codeguard_user_usage_route"
branch_labels = None
depends_on = None


# Target dimensionality for Gemini text-embedding-004. Kept as a
# constant so a future re-resize (e.g. switching to a 1024-d provider)
# is a one-line edit.
NEW_DIM = 768
OLD_DIM = 3072


def upgrade() -> None:
    # Drop HNSW indexes first — pgvector's HNSW index is typed by the
    # column dim, so dropping the column without dropping the index
    # produces a "cannot alter column referenced by index" error.
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_codeguard_doc_chunks_embedding_hnsw")

    # Each table: drop + recreate the embedding column. Using
    # `IF EXISTS` so the migration is idempotent if a previous half-run
    # left some columns already dropped.
    for table in ("chunks", "document_chunks", "codeguard_doc_chunks", "rfi_embeddings"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding")
        op.execute(f"ALTER TABLE {table} ADD COLUMN embedding vector({NEW_DIM})")

    # Recreate HNSW indexes at the new dim. `m=16, ef_construction=64`
    # are the defaults from the original migrations and a fine
    # starting point — re-tune later if recall drops below target.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_codeguard_doc_chunks_embedding_hnsw "
        "ON codeguard_doc_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_codeguard_doc_chunks_embedding_hnsw")

    for table in ("chunks", "document_chunks", "codeguard_doc_chunks", "rfi_embeddings"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding")
        op.execute(f"ALTER TABLE {table} ADD COLUMN embedding vector({OLD_DIM})")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_codeguard_doc_chunks_embedding_hnsw "
        "ON codeguard_doc_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
