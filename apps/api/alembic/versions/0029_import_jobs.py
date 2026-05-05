"""import_jobs + external_id on projects/suppliers — CSV/XLSX onboarding

Backs the `/settings/import` page. Real customer onboarding ships with
a spreadsheet of existing projects and suppliers; expecting them to
hand-key those into our forms one at a time is hostile. This migration
introduces:

  * `import_jobs` — one row per upload. Holds the parsed rows + per-row
    errors as JSONB blobs so a two-phase upload (preview → commit)
    works without a separate staging table.

  * `external_id` columns on `projects` and `suppliers`, plus a partial
    unique index on `(organization_id, external_id) WHERE external_id IS
    NOT NULL`. Lets us upsert on the customer's own row identifier so
    re-uploading the same CSV is idempotent: the second run UPDATEs
    instead of INSERTing duplicates.

Why the JSONB columns instead of a `import_rows` child table:
  * V1 caps imports at 1000 rows. JSONB is plenty for that.
  * Two-phase preview/commit means rows live for minutes, not days —
    no analytics, no FK access patterns to optimise for.
  * One table is one migration; one Alembic file is easier to revert.

We can promote `rows` and `errors` to a real child table once a tenant
asks for batched/streaming uploads >10k rows.

`status` enum kept as a free `text` column (with a check constraint) so
adding a phase later doesn't require an enum migration.

Revision ID: 0029_import_jobs
Revises: 0028_normalizer_rules
Create Date: 2026-05-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_import_jobs"
down_revision = "0028_normalizer_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- import_jobs table ----------
    op.create_table(
        "import_jobs",
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
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("entity", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'previewed'"),
        ),
        sa.Column("row_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("valid_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        # Per-row validation errors. Shape: [{"row_idx": int, "field": str|null, "message": str}, ...]
        sa.Column(
            "errors",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Validated rows pending commit. Shape: [{"external_id": "...", "name": "...", ...}, ...]
        sa.Column(
            "rows",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Number of rows ultimately written by `commit`. NULL until commit runs;
        # distinct from `valid_count` since a re-upload can match `external_id`
        # to the same target row twice (idempotent UPDATEs still count).
        sa.Column("committed_count", sa.Integer),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("committed_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "entity IN ('projects', 'suppliers')",
            name="ck_import_jobs_entity",
        ),
        sa.CheckConstraint(
            "status IN ('previewed', 'committed', 'failed')",
            name="ck_import_jobs_status",
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND valid_count >= 0 AND error_count >= 0",
            name="ck_import_jobs_counts_nonneg",
        ),
    )
    op.create_index(
        "ix_import_jobs_org_created",
        "import_jobs",
        ["organization_id", sa.text("created_at DESC")],
    )

    op.execute("ALTER TABLE import_jobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_import_jobs ON import_jobs
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ---------- external_id columns + partial unique index ----------
    #
    # `projects.organization_id` is nullable in 0001_core (legacy from the
    # platform-projects-only era — see migration 0021 for the same RLS-fix
    # discussion). For the import natural key we only care when
    # `organization_id` IS NOT NULL anyway; the partial index handles that.
    op.add_column("projects", sa.Column("external_id", sa.Text, nullable=True))
    op.create_index(
        "ix_projects_org_external_id",
        "projects",
        ["organization_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    # `suppliers.organization_id` is also nullable — global suppliers (e.g.
    # the system-seeded list of major Vietnamese cement plants) have NULL.
    # The partial index excludes those: a tenant-imported supplier with
    # external_id "ACME-42" coexists with a global "ACME-42" cleanly, and
    # two tenants can both have their own "ACME-42" without colliding.
    op.add_column("suppliers", sa.Column("external_id", sa.Text, nullable=True))
    op.create_index(
        "ix_suppliers_org_external_id",
        "suppliers",
        ["organization_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND organization_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_suppliers_org_external_id", table_name="suppliers")
    op.drop_column("suppliers", "external_id")
    op.drop_index("ix_projects_org_external_id", table_name="projects")
    op.drop_column("projects", "external_id")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_import_jobs ON import_jobs")
    op.drop_index("ix_import_jobs_org_created", table_name="import_jobs")
    op.drop_table("import_jobs")
