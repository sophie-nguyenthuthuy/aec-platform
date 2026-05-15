"""SubcontractorPortal — nhà thầu phụ truy cập qua token.

Vietnamese construction reality: tổng thầu thuê 5-20 nhà thầu phụ
trên mỗi dự án (hệ MEP, hoàn thiện, cảnh quan, …). Subs hiện liên
lạc với tổng thầu qua Zalo / email / điện thoại — không có cách
xem trạng thái nhiệm vụ tập trung, không có audit trail khi sub
báo tiến độ.

This module gives each subcontractor a **token-based portal** at
/subcontractor/{token} (public route, no Supabase login needed)
where they can:
  * See their own assignments on this project
  * Mark progress (percent + status + photos)
  * View payment status (read-only) from cashflow_entries

The tổng thầu (admin) mints tokens once per (subcontractor, project)
pair. Token TTL default 365 days (a project's lifecycle); rotation
on demand.

Two tables:
  * `subcontractor_portal_grants` — token registry. One row per
    (organization, subcontractor_email, project). Stores hashed
    token + expiry + last-used-at for audit.
  * `subcontractor_assignments` — work scopes assigned to one
    subcontractor. Per-assignment progress updates flow through
    here. Cross-references to schedule_activities (link to Gantt
    item if scoped that tight).

Revision ID: 0054_subcontractor_portal
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054_subcontractor_portal"
down_revision: Union[str, None] = "0053_safety_toolbox"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "subcontractor_portal_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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
        # Subcontractor identifying info — kept as plain text (no
        # Supabase user). Email is the natural key + used in audit.
        sa.Column("subcontractor_name", sa.Text, nullable=False),
        sa.Column("subcontractor_email", sa.Text, nullable=False),
        sa.Column("subcontractor_phone", sa.Text, nullable=True),
        # SHA-256 hex of the raw token. The raw token only exists in
        # transit (returned to caller on mint, lives in the URL the
        # admin pastes into Zalo). DB never stores the raw form —
        # a leaked DB dump can't be used to log in.
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # One subcontractor email can have at most one ACTIVE token
        # per project. Partial unique enforces this (allow re-mint
        # after revocation).
        sa.Index(
            "ix_subportal_grants_active_email_project",
            "organization_id",
            "project_id",
            "subcontractor_email",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )

    op.create_table(
        "subcontractor_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subcontractor_portal_grants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("contract_value_vnd", sa.BigInteger, nullable=True),
        sa.Column("planned_start", sa.Date, nullable=True),
        sa.Column("planned_finish", sa.Date, nullable=True),
        # Optional FK to schedule_activities for fine-grained Gantt link
        sa.Column(
            "schedule_activity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_activities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Sub-reported progress (0-100)
        sa.Column("percent_complete", sa.Integer, nullable=False, server_default="0"),
        # not_started | in_progress | review_needed | complete | blocked
        sa.Column("status", sa.Text, nullable=False, server_default="not_started"),
        sa.Column("sub_last_note", sa.Text, nullable=True),
        sa.Column("sub_last_update_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "percent_complete >= 0 AND percent_complete <= 100",
            name="ck_subassign_percent_bounds",
        ),
        sa.CheckConstraint(
            "status IN ('not_started', 'in_progress', 'review_needed', 'complete', 'blocked')",
            name="ck_subassign_status",
        ),
    )
    op.create_index(
        "ix_subassignments_grant",
        "subcontractor_assignments",
        ["grant_id"],
    )
    op.create_index(
        "ix_subassignments_project",
        "subcontractor_assignments",
        ["project_id"],
    )

    op.create_table(
        "subcontractor_progress_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subcontractor_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Audit info — who from the sub side reported (the token's email)
        sa.Column("reported_by_email", sa.Text, nullable=False),
        sa.Column("reported_by_ip", sa.Text, nullable=True),
        sa.Column("percent_complete", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("photo_file_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_subprogress_assignment_created",
        "subcontractor_progress_events",
        ["assignment_id", "created_at"],
    )

    # ---- RLS on the two tenant-scoped tables.
    # NOTE: We intentionally do NOT enable RLS on
    # subcontractor_portal_grants for token verification because
    # the public-portal endpoint runs WITHOUT a tenant context
    # (the token IS the auth signal). The router uses
    # AdminSessionFactory for that path; tenant-isolation is enforced
    # at the application layer via WHERE token_hash = $1 + project_id
    # FK to the org.
    for table in ("subcontractor_assignments", "subcontractor_progress_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table}
              ON {table}
              USING (organization_id = current_setting('app.current_org_id', true)::uuid)
              WITH CHECK (organization_id = current_setting('app.current_org_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("subcontractor_progress_events")
    op.drop_table("subcontractor_assignments")
    op.drop_table("subcontractor_portal_grants")
