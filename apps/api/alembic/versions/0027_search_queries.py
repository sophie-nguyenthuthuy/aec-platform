"""search_queries: telemetry for the cross-module search endpoint

Closes the loop on bucket-2 search work: with `matched_on` provenance
visible in the UI and now query telemetry persisted, we can tell:

  * Which queries land empty (signal: retrieval needs tuning, or the
    user wants a module/scope we haven't indexed).
  * Which scopes get used most (drives where to invest hybrid-retrieval
    polish next).
  * Whether hybrid is actually winning vs keyword-only (the
    `matched_distribution` JSONB carries the per-arm hit counts).

Schema rationale:

  * `query` is capped at 200 chars at the schema layer too, mirroring
    the `SearchRequest.query` Field max_length. Anything longer is
    almost certainly garbage.
  * `scopes` stores the literal scope set the caller asked for (or
    NULL when they let the server default to "all"). Lets the
    analytics page distinguish "user filtered to documents only" from
    "all scopes searched and only documents matched".
  * `top_scope` is the scope of the highest-ranked result. NULL when
    the query returned zero results — that's the no-result signal.
  * `matched_distribution` is `{"keyword": n, "vector": n, "both": n}`
    counting how many rows in the response landed via each provenance.
    NULL when no results.
  * `(organization_id, created_at DESC)` index drives the dominant
    "recent queries for this org" analytics query.
  * `project_id` is nullable — many searches aren't project-scoped
    (Cmd+K palette use case).

RLS: standard tenant-isolation with WITH CHECK. The analytics endpoint
is admin-gated at the API layer; RLS is belt-and-suspenders.

Retention: not enforced in this migration. A future cron will trim
rows older than e.g. 180d so the table doesn't grow unboundedly. For
now, an org running 1k searches/day produces ~30k rows/month, which
is trivial.

Revision ID: 0027_search_queries
Revises: 0026_codeguard_quota_audit_log
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0027_search_queries"
down_revision = "0026_codeguard_quota_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_queries",
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
        sa.Column("query", sa.Text, nullable=False),
        # Empty array = caller did NOT pass `scopes` (defaulted to all).
        # We use `[]` rather than NULL so analytics queries don't have
        # to special-case both "missing array" and "empty array".
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
        ),
        sa.Column("result_count", sa.Integer, nullable=False),
        sa.Column("top_scope", sa.Text),
        sa.Column("matched_distribution", postgresql.JSONB),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(query) <= 200", name="ck_search_queries_query_len"),
        sa.CheckConstraint("result_count >= 0", name="ck_search_queries_count_nonneg"),
    )
    # Hot path for /analytics: "recent queries for org X".
    op.create_index(
        "ix_search_queries_org_created",
        "search_queries",
        ["organization_id", sa.text("created_at DESC")],
    )
    # Drill-down: "queries that returned 0 hits in last N days" — the
    # most-actionable analytics view. Partial index keeps it tiny.
    op.create_index(
        "ix_search_queries_no_result",
        "search_queries",
        ["organization_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("result_count = 0"),
    )

    op.execute("ALTER TABLE search_queries ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_search_queries ON search_queries
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_search_queries ON search_queries")
    op.drop_index("ix_search_queries_no_result", table_name="search_queries")
    op.drop_index("ix_search_queries_org_created", table_name="search_queries")
    op.drop_table("search_queries")
