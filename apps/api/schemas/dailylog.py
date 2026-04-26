"""Pydantic schemas for the DailyLog module."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class DailyLogStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"


class ObservationKind(StrEnum):
    risk = "risk"
    issue = "issue"
    delay = "delay"
    milestone = "milestone"
    safety = "safety"
    quality = "quality"
    productivity = "productivity"


class ObservationSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ObservationSource(StrEnum):
    manual = "manual"
    llm_extracted = "llm_extracted"
    siteeye_hit = "siteeye_hit"


class ObservationStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    dismissed = "dismissed"


class EquipmentState(StrEnum):
    active = "active"
    idle = "idle"
    broken = "broken"
    left_site = "left_site"


# ---------- Manpower ----------


class ManpowerEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID | None = None
    trade: str
    headcount: int = Field(ge=0)
    hours_worked: float | None = None
    foreman: str | None = None
    notes: str | None = None


# ---------- Equipment ----------


class EquipmentEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID | None = None
    name: str
    quantity: int = Field(default=1, ge=0)
    hours_used: float | None = None
    state: EquipmentState | str = EquipmentState.active
    notes: str | None = None


# ---------- Observations ----------


class ObservationCreate(BaseModel):
    kind: ObservationKind
    severity: ObservationSeverity = ObservationSeverity.medium
    description: str
    source: ObservationSource = ObservationSource.manual
    related_safety_incident_id: UUID | None = None
    notes: str | None = None


class ObservationUpdate(BaseModel):
    kind: ObservationKind | None = None
    severity: ObservationSeverity | None = None
    description: str | None = None
    status: ObservationStatus | None = None
    notes: str | None = None


class Observation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    log_id: UUID
    kind: ObservationKind | str
    severity: ObservationSeverity | str
    description: str
    source: ObservationSource | str
    related_safety_incident_id: UUID | None = None
    status: ObservationStatus | str
    resolved_at: datetime | None = None
    notes: str | None = None
    created_at: datetime


# ---------- DailyLog ----------


class DailyLogCreate(BaseModel):
    project_id: UUID
    log_date: date
    weather: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    work_completed: str | None = None
    issues_observed: str | None = None
    manpower: list[ManpowerEntry] = Field(default_factory=list)
    equipment: list[EquipmentEntry] = Field(default_factory=list)
    auto_extract: bool = True


class DailyLogUpdate(BaseModel):
    weather: dict[str, Any] | None = None
    narrative: str | None = None
    work_completed: str | None = None
    issues_observed: str | None = None
    status: DailyLogStatus | None = None
    manpower: list[ManpowerEntry] | None = None
    equipment: list[EquipmentEntry] | None = None


class DailyLogSummary(BaseModel):
    """Compact projection used by the list endpoint."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    log_date: date
    status: DailyLogStatus | str
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    created_at: datetime
    # Cheap aggregates merged in by the router:
    total_headcount: int = 0
    open_observations: int = 0
    high_severity_observations: int = 0


class DailyLogDetail(BaseModel):
    summary: DailyLogSummary
    weather: dict[str, Any] = Field(default_factory=dict)
    narrative: str | None = None
    work_completed: str | None = None
    issues_observed: str | None = None
    manpower: list[ManpowerEntry] = Field(default_factory=list)
    equipment: list[EquipmentEntry] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    """Trigger params for POST /logs/{id}/extract."""

    force: bool = False


class PatternsResponse(BaseModel):
    """Aggregated patterns over a date range."""

    project_id: UUID
    date_from: date
    date_to: date
    days_observed: int
    avg_headcount: float
    issue_count_by_kind: dict[str, int] = Field(default_factory=dict)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    weather_anomaly_days: list[dict[str, Any]] = Field(default_factory=list)
    most_common_observations: list[dict[str, Any]] = Field(default_factory=list)
