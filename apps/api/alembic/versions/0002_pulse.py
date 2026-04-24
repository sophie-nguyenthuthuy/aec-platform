"""ProjectPulse tables (tasks, milestones, change_orders, meeting_notes, client_reports)

Revision ID: 0002_pulse
Revises: 0001_core
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_pulse"
down_revision = "0001_core"
branch_labels = None
depends_on = None


PULSE_TABLES = ("tasks", "milestones", "change_orders", "meeting_notes", "client_reports")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="todo"),
        sa.Column("priority", sa.Text, nullable=False, server_default="normal"),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("phase", sa.Text),
        sa.Column("discipline", sa.Text),
        sa.Column("start_date", sa.Date),
        sa.Column("due_date", sa.Date),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("position", sa.Numeric),
        sa.Column("tags", postgresql.ARRAY(sa.Text), server_default=sa.text("ARRAY[]::text[]")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('todo','in_progress','review','done','blocked')", name="ck_tasks_status"),
    )
    op.create_index("ix_tasks_org_project", "tasks", ["organization_id", "project_id"])
    op.create_index("ix_tasks_assignee", "tasks", ["assignee_id"])
    op.create_index("ix_tasks_phase_status", "tasks", ["project_id", "phase", "status"])

    op.create_table(
        "milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="upcoming"),
        sa.Column("achieved_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("status IN ('upcoming','achieved','missed')", name="ck_milestones_status"),
    )
    op.create_index("ix_milestones_project_due", "milestones", ["project_id", "due_date"])

    op.create_table(
        "change_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("initiator", sa.Text),
        sa.Column("cost_impact_vnd", sa.BigInteger),
        sa.Column("schedule_impact_days", sa.Integer),
        sa.Column("ai_analysis", postgresql.JSONB),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_cos_status"),
        sa.UniqueConstraint("project_id", "number", name="uq_cos_project_number"),
    )
    op.create_index("ix_cos_project_status", "change_orders", ["project_id", "status"])

    op.create_table(
        "meeting_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meeting_date", sa.Date, nullable=False),
        sa.Column("attendees", postgresql.ARRAY(sa.Text), server_default=sa.text("ARRAY[]::text[]")),
        sa.Column("raw_notes", sa.Text),
        sa.Column("ai_structured", postgresql.JSONB),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_meeting_notes_project_date", "meeting_notes", ["project_id", "meeting_date"])

    op.create_table(
        "client_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_date", sa.Date, nullable=False),
        sa.Column("period", sa.Text),
        sa.Column("content", postgresql.JSONB),
        sa.Column("rendered_html", sa.Text),
        sa.Column("pdf_url", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("sent_to", postgresql.ARRAY(sa.Text)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('draft','sent','archived')", name="ck_reports_status"),
    )
    op.create_index("ix_reports_project_date", "client_reports", ["project_id", "report_date"])

    for table in PULSE_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in reversed(PULSE_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
