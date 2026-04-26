"""dailylog tables

Tables created:
  * daily_logs (uniq project_id+log_date)
  * daily_log_manpower
  * daily_log_equipment
  * daily_log_observations

RLS enabled on all four. The `related_safety_incident_id` FK lets a
SiteEye sync job stamp daily-log observations against the source
incident; ON DELETE SET NULL keeps the observation alive even if the
incident is archived.

Revision ID: 0013_dailylog
Revises: 0012_submittals
Create Date: 2026-04-26
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0013_dailylog"
down_revision = "0012_submittals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_logs",
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
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("weather", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "supervisor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("narrative", sa.Text()),
        sa.Column("work_completed", sa.Text()),
        sa.Column("issues_observed", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("extracted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "project_id", "log_date", name="uq_daily_logs_project_date"
        ),
    )
    op.create_index(
        "ix_daily_logs_project_date",
        "daily_logs",
        ["project_id", "log_date"],
    )
    op.create_index(
        "ix_daily_logs_status", "daily_logs", ["organization_id", "status"]
    )

    op.create_table(
        "daily_log_manpower",
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
            "log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade", sa.Text(), nullable=False),
        sa.Column("headcount", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("hours_worked", sa.Numeric(6, 2)),
        sa.Column("foreman", sa.Text()),
        sa.Column("notes", sa.Text()),
    )
    op.create_index(
        "ix_daily_log_manpower_log", "daily_log_manpower", ["log_id"]
    )

    op.create_table(
        "daily_log_equipment",
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
            "log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("hours_used", sa.Numeric(6, 2)),
        sa.Column("state", sa.Text(), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text()),
    )
    op.create_index(
        "ix_daily_log_equipment_log", "daily_log_equipment", ["log_id"]
    )

    op.create_table(
        "daily_log_observations",
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
            "log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="medium"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column(
            "related_safety_incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("safety_incidents.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_daily_log_observations_log",
        "daily_log_observations",
        ["log_id", "kind"],
    )
    op.create_index(
        "ix_daily_log_observations_severity",
        "daily_log_observations",
        ["organization_id", "severity", "status"],
    )

    for table in (
        "daily_logs",
        "daily_log_manpower",
        "daily_log_equipment",
        "daily_log_observations",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in (
        "daily_log_observations",
        "daily_log_equipment",
        "daily_log_manpower",
        "daily_logs",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
