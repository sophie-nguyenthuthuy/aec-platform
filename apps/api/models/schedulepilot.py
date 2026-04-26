"""SchedulePilot — Gantt/CPM scheduling, baseline-vs-actual, AI risk forecasting.

Tables
------
* `schedules` — one or more per project (re-baselining = new schedule). The
  `baseline_set_at` timestamp is the freeze point; once set, baseline_*
  columns on activities are no longer auto-updated.
* `activities` — atomic schedule items (tasks/milestones/summary buckets).
  Both planned and baseline date fields exist so we can show drift.
* `schedule_dependencies` — FS/SS/FF/SF + lag (lead = negative lag).
* `schedule_risk_assessments` — output of the LLM pipeline. Stores the
  computed CPM critical path, computed slip metrics, and the model's
  top-N narrated risks for audit + back-fill.

Why not reuse pulse.tasks
-------------------------
Pulse tasks are kanban-style work items with no scheduling structure
(no predecessors, no baseline, no CPM). They are effectively the "what
the team is doing this week" view; SchedulePilot is the "what the
project committed to vs what's actually happening" view. Keeping them
separate means re-baselining doesn't disturb the daily kanban and a
team can adopt SchedulePilot without losing pulse history.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # draft → baselined → active → archived
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    # Frozen on POST /baseline; null until then.
    baseline_set_at: Mapped[datetime | None] = mapped_column(TZ)
    # The "as-of" date that progress numbers were last updated to.
    data_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class Activity(Base):
    __tablename__ = "schedule_activities"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    schedule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    # WBS code (1.2.3) — unique per schedule.
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # task | milestone | summary
    activity_type: Mapped[str] = mapped_column(Text, nullable=False, default="task")
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_finish: Mapped[date | None] = mapped_column(Date)
    planned_duration_days: Mapped[int | None] = mapped_column(Integer)
    baseline_start: Mapped[date | None] = mapped_column(Date)
    baseline_finish: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_finish: Mapped[date | None] = mapped_column(Date)
    # 0–100
    percent_complete: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    # not_started | in_progress | complete | on_hold
    status: Mapped[str] = mapped_column(Text, nullable=False, default="not_started")
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ScheduleDependency(Base):
    __tablename__ = "schedule_dependencies"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    predecessor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule_activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    successor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule_activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    # fs | ss | ff | sf
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False, default="fs")
    # Negative for lead, positive for lag.
    lag_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ScheduleRiskAssessment(Base):
    __tablename__ = "schedule_risk_assessments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    schedule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    generated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    model_version: Mapped[str | None] = mapped_column(Text)
    data_date_used: Mapped[date | None] = mapped_column(Date)
    # Computed: max activity slip on critical path (baseline → projected).
    overall_slip_days: Mapped[int] = mapped_column(Integer, default=0)
    # Best-effort confidence from the LLM (0–100).
    confidence_pct: Mapped[int | None] = mapped_column(Integer)
    # CPM critical path activity codes in topological order.
    critical_path_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # [{activity_id, code, name, expected_slip_days, reason, mitigation}]
    top_risks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Aggregate counters used as LLM input — kept for audit replay.
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
