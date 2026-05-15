"""SafetyToolboxTalks — Báo cáo họp an toàn đầu ca.

Vietnamese construction law (Nghị định 06/2021, Thông tư 04/2017
hướng dẫn) mandates a 5-15 minute safety briefing at shift start
for every construction site, with documented attendance + topic.
Failure to maintain records is a Sở Xây dựng inspection finding
(common fine: 5-15 triệu VNĐ per occurrence).

Schema:

  * `safety_toolbox_talks` — one row per briefing.
    Required by law: date, project, topic, presenter, attendees.
    Optional: hazards covered (free-form), PPE checked, signatures.
  * `safety_toolbox_attendance` — denormalised attendance ledger.
    One row per (talk, worker). Lets us answer "did 工人 X attend
    safety briefing on date Y?" cheaply for KTNN audits.

We intentionally do NOT model "workers" as a first-class entity
here — most VN construction crews use ad-hoc names + phone numbers
written on paper. The attendance ledger stores worker_name +
worker_phone as text. A future Workforce module can normalise this,
but blocking on that now would prevent customers from getting
compliance value today.

Revision ID: 0053_safety_toolbox
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053_safety_toolbox"
down_revision: Union[str, None] = "0052_cashflow"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "safety_toolbox_talks",
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
        # ngày tổ chức buổi briefing — UNIQUE per (project, date, shift)
        # to prevent accidental double-entry from two supervisors.
        sa.Column("held_on", sa.Date, nullable=False),
        # morning | afternoon | night — VN sites typically have
        # 2 shifts (sáng + chiều); 3-shift industrial sites need night.
        sa.Column("shift", sa.Text, nullable=False, server_default="morning"),
        # Topic — required. Short string like "Sử dụng dây an toàn khi
        # làm việc trên cao" or "Phòng cháy chữa cháy mùa khô".
        sa.Column("topic", sa.Text, nullable=False),
        # Free-form details of hazards discussed, mitigation rules.
        sa.Column("content_notes", sa.Text, nullable=True),
        # Người trình bày — usually the chỉ huy trưởng or HSE officer.
        sa.Column("presenter_name", sa.Text, nullable=False),
        sa.Column("presenter_role", sa.Text, nullable=True),
        # PPE state of the day — quick checklist JSONB:
        # {"helmets": "all", "vests": "all", "boots": "partial", "harness": "n/a"}
        sa.Column("ppe_checks", postgresql.JSONB, nullable=True),
        # Reference to a SiteEye visit — when the supervisor opened
        # the talk while doing the morning site walk-around.
        sa.Column(
            "siteeye_visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("site_visits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Photo of the signed-attendance sheet (Sở Xây dựng inspector
        # asks for this). Stored in files (MinIO/S3).
        sa.Column(
            "signature_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recorded_by",
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
        sa.CheckConstraint(
            "shift IN ('morning', 'afternoon', 'night')",
            name="ck_safety_talks_shift",
        ),
        sa.UniqueConstraint(
            "project_id", "held_on", "shift",
            name="uq_safety_talk_project_date_shift",
        ),
    )
    op.create_index(
        "ix_safety_talks_project_date",
        "safety_toolbox_talks",
        ["project_id", "held_on"],
    )

    op.create_table(
        "safety_toolbox_attendance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "talk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("safety_toolbox_talks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_name", sa.Text, nullable=False),
        sa.Column("worker_phone", sa.Text, nullable=True),
        sa.Column("worker_role", sa.Text, nullable=True),  # thợ hồ, thợ sắt, kỹ sư giám sát, ...
        sa.Column("subcontractor", sa.Text, nullable=True),  # tên nhà thầu phụ nếu có
        sa.Column("signed", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_safety_attendance_talk",
        "safety_toolbox_attendance",
        ["talk_id"],
    )
    # For "did worker phone X attend a talk in date range" queries
    op.create_index(
        "ix_safety_attendance_phone",
        "safety_toolbox_attendance",
        ["worker_phone"],
    )

    # ---- RLS ----
    for table in ("safety_toolbox_talks", "safety_toolbox_attendance"):
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
    op.drop_table("safety_toolbox_attendance")
    op.drop_table("safety_toolbox_talks")
