"""schedulepilot tables

Tables created:
  * schedules
  * schedule_activities
  * schedule_dependencies
  * schedule_risk_assessments

RLS:
  All four are tenant-scoped via `app.current_org_id`.

Revision ID: 0011_schedulepilot
Revises: 0010_app_role
Create Date: 2026-04-25
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0011_schedulepilot"
down_revision = "0010_app_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("baseline_set_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("data_date", sa.Date()),
        sa.Column("notes", sa.Text()),
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
    )
    op.create_index(
        "ix_schedules_project", "schedules", ["organization_id", "project_id"]
    )
    op.create_index("ix_schedules_status", "schedules", ["organization_id", "status"])

    op.create_table(
        "schedule_activities",
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
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=False, server_default="task"),
        sa.Column("planned_start", sa.Date()),
        sa.Column("planned_finish", sa.Date()),
        sa.Column("planned_duration_days", sa.Integer()),
        sa.Column("baseline_start", sa.Date()),
        sa.Column("baseline_finish", sa.Date()),
        sa.Column("actual_start", sa.Date()),
        sa.Column("actual_finish", sa.Date()),
        sa.Column(
            "percent_complete",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="not_started"
        ),
        sa.Column(
            "assignee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            "schedule_id", "code", name="uq_schedule_activities_code"
        ),
    )
    op.create_index(
        "ix_schedule_activities_schedule",
        "schedule_activities",
        ["schedule_id", "sort_order"],
    )
    op.create_index(
        "ix_schedule_activities_status",
        "schedule_activities",
        ["schedule_id", "status"],
    )

    op.create_table(
        "schedule_dependencies",
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
            "predecessor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "successor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relationship_type", sa.Text(), nullable=False, server_default="fs"
        ),
        sa.Column("lag_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "predecessor_id",
            "successor_id",
            name="uq_schedule_dependency_pair",
        ),
        sa.CheckConstraint(
            "predecessor_id <> successor_id",
            name="ck_schedule_dependency_no_self_loop",
        ),
    )
    op.create_index(
        "ix_schedule_dependencies_pred",
        "schedule_dependencies",
        ["predecessor_id"],
    )
    op.create_index(
        "ix_schedule_dependencies_succ",
        "schedule_dependencies",
        ["successor_id"],
    )

    op.create_table(
        "schedule_risk_assessments",
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
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("model_version", sa.Text()),
        sa.Column("data_date_used", sa.Date()),
        sa.Column(
            "overall_slip_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("confidence_pct", sa.Integer()),
        sa.Column(
            "critical_path_codes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "top_risks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "input_summary",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("notes", sa.Text()),
    )
    op.create_index(
        "ix_schedule_risk_assessments_schedule",
        "schedule_risk_assessments",
        ["schedule_id", "generated_at"],
    )

    # ---- RLS ----
    for table in (
        "schedules",
        "schedule_activities",
        "schedule_dependencies",
        "schedule_risk_assessments",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            "USING (organization_id = current_setting('app.current_org_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in (
        "schedule_risk_assessments",
        "schedule_dependencies",
        "schedule_activities",
        "schedules",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
