"""siteeye tables

Revision ID: 0003_siteeye
Revises: 0002_codeguard
Create Date: 2026-04-22
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_siteeye"
# Merge point for the three parallel 0002 heads (costpulse, pulse, winwork).
down_revision = ("0002_costpulse", "0002_pulse", "0002_winwork")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("location", postgresql.JSONB()),
        sa.Column("reported_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("weather", sa.Text()),
        sa.Column("workers_count", sa.Integer()),
        sa.Column("notes", sa.Text()),
        sa.Column("ai_summary", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_site_visits_org_project", "site_visits", ["organization_id", "project_id"])
    op.create_index("ix_site_visits_date", "site_visits", ["visit_date"])

    op.create_table(
        "site_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("site_visit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("site_visits.id", ondelete="CASCADE")),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("thumbnail_url", sa.Text()),
        sa.Column("taken_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("location", postgresql.JSONB()),
        sa.Column("tags", postgresql.ARRAY(sa.Text())),
        sa.Column("ai_analysis", postgresql.JSONB()),
        sa.Column("safety_status", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_site_photos_project", "site_photos", ["organization_id", "project_id"])
    op.create_index("ix_site_photos_visit", "site_photos", ["site_visit_id"])
    op.create_index("ix_site_photos_taken_at", "site_photos", ["taken_at"])
    op.create_index("ix_site_photos_safety", "site_photos", ["safety_status"])
    op.create_index("ix_site_photos_tags", "site_photos", ["tags"], postgresql_using="gin")

    op.create_table(
        "progress_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("overall_progress_pct", sa.Numeric()),
        sa.Column("phase_progress", postgresql.JSONB()),
        sa.Column("ai_notes", sa.Text()),
        sa.Column("photo_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "snapshot_date", name="uq_progress_snapshots_project_date"),
    )
    op.create_index("ix_progress_snapshots_project", "progress_snapshots", ["organization_id", "project_id"])

    op.create_table(
        "safety_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("incident_type", sa.Text()),
        sa.Column("severity", sa.Text()),
        sa.Column("photo_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("site_photos.id", ondelete="SET NULL")),
        sa.Column("detection_box", postgresql.JSONB()),
        sa.Column("ai_description", sa.Text()),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_safety_incidents_project", "safety_incidents", ["organization_id", "project_id"])
    op.create_index("ix_safety_incidents_status", "safety_incidents", ["status"])
    op.create_index("ix_safety_incidents_severity", "safety_incidents", ["severity"])
    op.create_index("ix_safety_incidents_detected", "safety_incidents", ["detected_at"])

    op.create_table(
        "weekly_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("content", postgresql.JSONB()),
        sa.Column("rendered_html", sa.Text()),
        sa.Column("pdf_url", sa.Text()),
        sa.Column("sent_to", postgresql.ARRAY(sa.Text())),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "week_start", name="uq_weekly_reports_project_week"),
    )
    op.create_index("ix_weekly_reports_project", "weekly_reports", ["organization_id", "project_id"])

    for table in ("site_visits", "site_photos", "progress_snapshots", "safety_incidents", "weekly_reports"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("weekly_reports", "safety_incidents", "progress_snapshots", "site_photos", "site_visits"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
