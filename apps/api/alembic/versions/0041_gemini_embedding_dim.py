"""Resize every pgvector column from 3072 → 768 dim for Gemini embeddings.

The original embedding pipeline used OpenAI's `text-embedding-3-large`
(3072 dim). The free-tier deploy pivots to Google Gemini's
`text-embedding-004` (768 dim). pgvector columns are typed by
dimensionality at create time — you cannot widen or narrow them in
place, and a stored 3072-d vector can't be coerced into a 768-d
column. So this migration:

  1. Drops every HNSW index that references an `embedding` or
     `embedding_half` column at the old dim.
  2. Drops every `embedding_half halfvec(3072)` generated sidecar
     column (from migrations 0007, 0009, 0012). These were optimisations
     for the 3072-d pipeline; the platform falls back to the base
     `embedding` column when the halfvec sidecar is absent
     (see services/search.py).
  3. Drops every `embedding vector(3072)` column (with CASCADE for
     safety) on the four tables that have one.
  4. Recreates each `embedding` column as `vector(768)`.
  5. Recreates HNSW indexes on the new `embedding` columns.

Existing embedding rows are NOT migrated — there is no transform from
3072-d OpenAI vectors to 768-d Gemini vectors. After this migration,
the embedding tables are empty in terms of vectors (but the metadata
rows, FKs, etc. stay). Re-run the seed (`make seed-demo` or
`make seed-codeguard-all`) to repopulate.

Tables touched:

  * `embeddings`        (created in 0001_core)
  * `document_chunks`   (created in 0004_drawbridge)         + halfvec sidecar (0007)
  * `regulation_chunks` (created in 0005_codeguard)          + halfvec sidecar (0009)
  * `rfi_embeddings`    (created in 0012_submittals)         + halfvec sidecar (0012)

Down-migration restores 3072-d columns and indexes for symmetry, but
again, embedding rows aren't preserved across either direction. The
halfvec sidecar columns are NOT restored on downgrade — re-applying
0007/0009/0012's halfvec adds would require running those migrations'
add-column blocks again, which is out of scope for this migration.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0041_gemini_embedding_dim"
down_revision = "0040_codeguard_user_usage_route"
branch_labels = None
depends_on = None


# Target dimensionality for Gemini text-embedding-004. Kept as a
# constant so a future re-resize (e.g. switching to a 1024-d provider)
# is a one-line edit.
NEW_DIM = 768
OLD_DIM = 3072

# Tables whose `embedding` column we resize. Maps to the source migration
# that originally created each one so the chain is traceable in git blame.
EMBEDDING_TABLES = (
    "embeddings",         # 0001_core
    "document_chunks",    # 0004_drawbridge
    "regulation_chunks",  # 0005_codeguard
    "rfi_embeddings",     # 0012_submittals
)

# HNSW indexes on `embedding` or `embedding_half` that we need to drop
# before mutating the column. Names use the conventions from the
# original migrations.
INDEXES_TO_DROP = (
    # vector(3072) base-column indexes
    "ix_embeddings_embedding_hnsw",
    "ix_document_chunks_embedding_hnsw",
    "ix_regulation_chunks_embedding_hnsw",
    # halfvec(3072) sidecar indexes
    "ix_document_chunks_embedding_half_hnsw",
    "ix_regulation_chunks_embedding_half_hnsw",
    "ix_rfi_embeddings_embedding_half_hnsw",
)

# Tables that have a halfvec(3072) generated `embedding_half` column
# we need to drop before the base `embedding` column can be resized.
HALFVEC_TABLES = (
    "document_chunks",    # 0007_drawbridge_hnsw
    "regulation_chunks",  # 0009_codeguard_hnsw
    "rfi_embeddings",     # 0012_submittals
)


def upgrade() -> None:
    # 1. Drop HNSW indexes — they're typed by column dim and would block
    #    column-type changes otherwise.
    for ix in INDEXES_TO_DROP:
        op.execute(f"DROP INDEX IF EXISTS {ix}")

    # 2. Drop halfvec generated sidecar columns. These are GENERATED
    #    ALWAYS AS (embedding::halfvec(3072)), so they depend on the
    #    base embedding column's type matching.
    for table in HALFVEC_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding_half")

    # 3. Drop + recreate the base `embedding` column at the new dim.
    #    CASCADE is defence-in-depth in case any future migration adds
    #    a dependent generated column we forgot to enumerate above.
    for table in EMBEDDING_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding CASCADE")
        op.execute(f"ALTER TABLE {table} ADD COLUMN embedding vector({NEW_DIM})")

    # 4. Recreate HNSW indexes on the resized embedding columns.
    #    `m=16, ef_construction=64` are the defaults from the original
    #    migrations and a fine starting point for the smaller dim too.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_embedding_hnsw "
        "ON embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_regulation_chunks_embedding_hnsw "
        "ON regulation_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    for ix in INDEXES_TO_DROP:
        op.execute(f"DROP INDEX IF EXISTS {ix}")

    for table in EMBEDDING_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding CASCADE")
        op.execute(f"ALTER TABLE {table} ADD COLUMN embedding vector({OLD_DIM})")

    # NB: halfvec sidecar columns are NOT restored on downgrade — see
    # module docstring.

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_embedding_hnsw "
        "ON embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_regulation_chunks_embedding_hnsw "
        "ON regulation_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
