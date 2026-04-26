"""Pydantic schemas for SchedulePilot.

Mirror of `models.schedulepilot` plus a handful of *Request/Response wrappers
for the endpoints that operate on the schedule rather than a single row
(baseline, risk-assessment).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class ScheduleStatus(StrEnum):
    draft = "draft"
    baselined = "baselined"
    active = "active"
    archived = "archived"


class ActivityType(StrEnum):
    task = "task"
    milestone = "milestone"
    summary = "summary"


class ActivityStatus(StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    complete = "complete"
    on_hold = "on_hold"


class DependencyType(StrEnum):
    fs = "fs"
    ss = "ss"
    ff = "ff"
    sf = "sf"


# ---------- Schedule ----------


class ScheduleCreate(BaseModel):
    project_id: UUID
    name: str
    notes: str | None = None
    data_date: date | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    status: ScheduleStatus | None = None
    notes: str | None = None
    data_date: date | None = None


class ScheduleSummary(BaseModel):
    """Compact projection used by the list endpoint and project detail."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    status: ScheduleStatus | str
    baseline_set_at: datetime | None = None
    data_date: date | None = None
    created_at: datetime
    updated_at: datetime
    # Counters merged in by the router for cheap card-style rendering.
    activity_count: int = 0
    on_critical_path_count: int = 0
    behind_schedule_count: int = 0
    percent_complete: float = 0.0


# ---------- Activities ----------


class ActivityCreate(BaseModel):
    code: str
    name: str
    activity_type: ActivityType = ActivityType.task
    planned_start: date | None = None
    planned_finish: date | None = None
    planned_duration_days: int | None = None
    assignee_id: UUID | None = None
    notes: str | None = None
    sort_order: int = 0


class ActivityUpdate(BaseModel):
    name: str | None = None
    activity_type: ActivityType | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    planned_duration_days: int | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    percent_complete: float | None = Field(default=None, ge=0, le=100)
    status: ActivityStatus | None = None
    assignee_id: UUID | None = None
    notes: str | None = None
    sort_order: int | None = None


class Activity(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    schedule_id: UUID
    code: str
    name: str
    activity_type: ActivityType | str
    planned_start: date | None = None
    planned_finish: date | None = None
    planned_duration_days: int | None = None
    baseline_start: date | None = None
    baseline_finish: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    percent_complete: float = 0.0
    status: ActivityStatus | str
    assignee_id: UUID | None = None
    notes: str | None = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


# ---------- Dependencies ----------


class DependencyCreate(BaseModel):
    predecessor_id: UUID
    successor_id: UUID
    relationship_type: DependencyType = DependencyType.fs
    lag_days: int = 0


class Dependency(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    predecessor_id: UUID
    successor_id: UUID
    relationship_type: DependencyType | str
    lag_days: int = 0
    created_at: datetime


# ---------- Risk assessment ----------


class TopRisk(BaseModel):
    activity_id: UUID
    code: str
    name: str
    expected_slip_days: int
    reason: str
    mitigation: str


class RiskAssessmentCreate(BaseModel):
    """Trigger params for POST .../risk-assessment.

    `force` re-runs even if a recent assessment exists.
    """

    force: bool = False


class RiskAssessment(BaseModel):
    # `model_version` collides with Pydantic's `model_` protected namespace —
    # opt out so the field name stays close to the column name in the DB.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: UUID
    organization_id: UUID
    schedule_id: UUID
    generated_at: datetime
    model_version: str | None = None
    data_date_used: date | None = None
    overall_slip_days: int = 0
    confidence_pct: int | None = None
    critical_path_codes: list[str] = Field(default_factory=list)
    top_risks: list[dict[str, Any]] = Field(default_factory=list)
    input_summary: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


# ---------- Aggregates ----------


class ScheduleDetail(BaseModel):
    """Full schedule + nested activities + dependencies + latest risk."""

    schedule: ScheduleSummary
    activities: list[Activity] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    latest_risk_assessment: RiskAssessment | None = None


class BaselineRequest(BaseModel):
    """Lock the current planned_* dates as baseline_* and flip status."""

    note: str | None = None
