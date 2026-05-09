"""audit_events — append-only "who did what" log for sensitive writes

Pairs with the RBAC layer landed in `0017`/`0021`: every endpoint gated
by `require_min_role(...)` now emits an audit row when it succeeds. Use
cases:

  * Compliance / customer trust: "show me everyone who approved a
    change order on Tower A in the last 30 days".
  * Debugging: "the budget jumped 20% — who approved that estimate
    revision and when?"
  * Security: "did anyone get demoted to viewer right before this
    leak?"

Schema rationale:
  * `actor_user_id` is nullable so we can record system-driven events
    (cron jobs, parallel-session imports) without inventing a synthetic
    user.
  * `before` / `after` are JSONB diffs — the *minimal* delta the caller
    wants to record, NOT a full row dump (avoids accidentally writing
    PII into the audit table). Routers populate them with handfuls of
    fields like `{"role": "member"}`.
  * `(organization_id, created_at DESC)` index supports the dominant
    query "recent audit events for org X".
  * `(resource_type, resource_id)` index supports drilling into one
    object's history.
  * Append-only: no `updated_at`, no UPDATE handlers anywhere. If we
    ever need to redact, we'll do it via a separate `audit_redactions`
    table that overlays. This keeps the integrity guarantee strong.

RLS: standard tenant isolation with `WITH CHECK`. The audit-query
endpoint is admin-gated at the API layer, so RLS is belt-and-suspenders.

Revision ID: 0022_audit_events
Revises: 0021_rls_with_check_everywhere
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0022_audit_events"
down_revision = "0021_rls_with_check_everywhere"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
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
        # Nullable so cron / system actors don't need a synthetic user.
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # `action` is a free-form verb-y string. We could enum it, but
        # the registry of actions evolves with every new module — a
        # CHECK constraint becomes a migration toll. Lint at the call
        # site instead (the `audit.record(...)` helper accepts a typed
        # `AuditAction` literal that's the single source of truth).
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "before",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "after",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Network metadata for forensic value. Never required, often
        # populated from `request.client.host` + the UA header.
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    # Hot path: "recent events for org X".
    op.create_index(
        "ix_audit_events_org_created",
        "audit_events",
        ["organization_id", sa.text("created_at DESC")],
    )
    # Drill-down: "show me everything that happened to this resource".
    op.create_index(
        "ix_audit_events_resource",
        "audit_events",
        ["resource_type", "resource_id"],
    )

    # RLS — same shape as every other tenant-scoped table after 0021.
    # Both USING and WITH CHECK so the platform-wide invariant holds.
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_audit_events ON audit_events
            USING (organization_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_audit_events ON audit_events")
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_index("ix_audit_events_org_created", table_name="audit_events")
    op.drop_table("audit_events")
