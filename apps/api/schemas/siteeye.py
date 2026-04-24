"""Pydantic schemas for SITEEYE module."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- Enums ----------

class SafetyStatus(str, Enum):
    clear = "clear"
    warning = "warning"
    critical = "critical"


class IncidentType(str, Enum):
    no_ppe = "no_ppe"
    unsafe_scaffold = "unsafe_scaffold"
    open_trench = "open_trench"
    fire_hazard = "fire_hazard"
    electrical_hazard = "electrical_hazard"


class IncidentSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IncidentStatus(str, Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
    dismissed = "dismissed"


class ConstructionPhase(str, Enum):
    site_prep = "site_prep"
    foundation = "foundation"
    structure = "structure"
    envelope = "envelope"
    mep = "mep"
    finishes = "finishes"
    exterior = "exterior"
    handover = "handover"


# ---------- Geo ----------

class GeoLocation(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None


# ---------- Site visits ----------

class SiteVisitCreate(BaseModel):
    project_id: UUID
    visit_date: date
    location: GeoLocation | None = None
    weather: str | None = None
    workers_count: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)


class SiteVisit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    visit_date: date
    location: GeoLocation | None = None
    reported_by: UUID | None = None
    weather: str | None = None
    workers_count: int | None = None
    notes: str | None = None
    ai_summary: str | None = None
    photo_count: int = 0
    created_at: datetime


class VisitListFilters(BaseModel):
    project_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# ---------- Photos ----------

class PhotoDetection(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: list[float] = Field(description="[x, y, w, h] normalized 0-1")


class PhotoAIAnalysis(BaseModel):
    description: str | None = None
    detected_elements: list[str] = Field(default_factory=list)
    safety_flags: list[PhotoDetection] = Field(default_factory=list)
    progress_indicators: dict[str, Any] = Field(default_factory=dict)
    phase: ConstructionPhase | None = None
    completion_hint: float | None = Field(default=None, ge=0.0, le=1.0)


class PhotoUploadItem(BaseModel):
    file_id: UUID
    taken_at: datetime | None = None
    location: GeoLocation | None = None
    thumbnail_url: str | None = None


class PhotoBatchUploadRequest(BaseModel):
    project_id: UUID
    site_visit_id: UUID | None = None
    photos: list[PhotoUploadItem] = Field(min_length=1, max_length=50)


class SitePhoto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    site_visit_id: UUID | None = None
    file_id: UUID | None = None
    thumbnail_url: str | None = None
    taken_at: datetime | None = None
    location: GeoLocation | None = None
    tags: list[str] = Field(default_factory=list)
    ai_analysis: PhotoAIAnalysis | None = None
    safety_status: SafetyStatus | None = None
    created_at: datetime


class PhotoBatchUploadResponse(BaseModel):
    accepted: int
    photo_ids: list[UUID]
    job_id: UUID


class PhotoListFilters(BaseModel):
    project_id: UUID | None = None
    site_visit_id: UUID | None = None
    tags: list[str] | None = None
    safety_status: SafetyStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# ---------- Progress ----------

class PhaseProgress(BaseModel):
    phase: ConstructionPhase
    pct: float = Field(ge=0.0, le=100.0)


class ProgressSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    snapshot_date: date
    overall_progress_pct: float
    phase_progress: dict[str, float]
    ai_notes: str | None = None
    photo_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime


class ProgressTimeline(BaseModel):
    project_id: UUID
    snapshots: list[ProgressSnapshot]
    baseline_schedule: dict[str, Any] | None = None
    schedule_status: Literal["on_track", "ahead", "behind", "unknown"] = "unknown"


# ---------- Safety ----------

class SafetyIncident(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    detected_at: datetime
    incident_type: IncidentType
    severity: IncidentSeverity
    photo_id: UUID | None = None
    detection_box: dict[str, Any] | None = None
    ai_description: str | None = None
    status: IncidentStatus
    acknowledged_by: UUID | None = None
    resolved_at: datetime | None = None


class SafetyIncidentFilters(BaseModel):
    project_id: UUID | None = None
    status: IncidentStatus | None = None
    severity: IncidentSeverity | None = None
    incident_type: IncidentType | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AcknowledgeIncidentRequest(BaseModel):
    notes: str | None = None
    resolve: bool = False


# ---------- Weekly reports ----------

class ReportKPIs(BaseModel):
    days_elapsed: int
    days_remaining: int | None = None
    schedule_status: Literal["on_track", "ahead", "behind", "unknown"]
    overall_progress_pct: float


class ReportContent(BaseModel):
    executive_summary: str
    progress_this_week: dict[str, Any]
    safety_summary: dict[str, Any]
    issues_and_risks: list[str] = Field(default_factory=list)
    next_week_plan: list[str] = Field(default_factory=list)
    photos_highlighted: list[UUID] = Field(default_factory=list)
    kpis: ReportKPIs


class WeeklyReportGenerateRequest(BaseModel):
    project_id: UUID
    week_start: date
    week_end: date


class WeeklyReport(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    week_start: date
    week_end: date
    content: ReportContent | None = None
    rendered_html: str | None = None
    pdf_url: str | None = None
    sent_to: list[str] = Field(default_factory=list)
    sent_at: datetime | None = None
    created_at: datetime


class WeeklyReportListFilters(BaseModel):
    project_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SendReportRequest(BaseModel):
    recipients: list[str] = Field(min_length=1, max_length=50)
    subject: str | None = None
    message: str | None = Field(default=None, max_length=2000)
