"""Pydantic schemas for CODEGUARD module."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class RegulationCategory(StrEnum):
    fire_safety = "fire_safety"
    accessibility = "accessibility"
    structure = "structure"
    zoning = "zoning"
    energy = "energy"


class CheckType(StrEnum):
    manual_query = "manual_query"
    auto_scan = "auto_scan"
    permit_checklist = "permit_checklist"


class CheckStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Severity(StrEnum):
    critical = "critical"
    major = "major"
    minor = "minor"


class FindingStatus(StrEnum):
    fail = "FAIL"
    warn = "WARN"
    pass_ = "PASS"


class ChecklistItemStatus(StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    not_applicable = "not_applicable"


# ---------- Regulations ----------


class RegulationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    country_code: str
    jurisdiction: str | None = None
    code_name: str
    category: RegulationCategory | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    source_url: str | None = None
    language: str = "vi"


class RegulationSection(BaseModel):
    section_ref: str
    title: str | None = None
    content: str


class RegulationDetail(RegulationSummary):
    content: dict[str, Any] | None = None
    sections: list[RegulationSection] = Field(default_factory=list)


# ---------- Query (Q&A) ----------


class QueryRequest(BaseModel):
    project_id: UUID | None = None
    question: str = Field(min_length=3, max_length=2000)
    language: Literal["vi", "en"] | None = None
    jurisdiction: str | None = None
    categories: list[RegulationCategory] | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class Citation(BaseModel):
    regulation_id: UUID
    regulation: str
    section: str
    excerpt: str
    source_url: str | None = None


class QueryResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[Citation]
    related_questions: list[str] = Field(default_factory=list)
    check_id: UUID | None = None


# ---------- Auto-scan ----------


class ProjectParameters(BaseModel):
    project_type: str = Field(description="residential | commercial | mixed_use | industrial | public")
    use_class: str | None = None
    total_area_m2: float | None = Field(default=None, ge=0)
    floors_above: int | None = Field(default=None, ge=0)
    floors_below: int | None = Field(default=None, ge=0)
    max_height_m: float | None = Field(default=None, ge=0)
    occupancy: int | None = Field(default=None, ge=0)
    location: dict[str, Any] | None = None
    features: dict[str, Any] | None = None


class ScanRequest(BaseModel):
    project_id: UUID
    parameters: ProjectParameters
    categories: list[RegulationCategory] | None = None


class Finding(BaseModel):
    status: FindingStatus
    severity: Severity
    category: RegulationCategory
    title: str
    description: str
    resolution: str | None = None
    citation: Citation | None = None


class ScanResponse(BaseModel):
    check_id: UUID
    status: CheckStatus
    total: int
    pass_count: int
    warn_count: int
    fail_count: int
    findings: list[Finding]


# ---------- Permit checklist ----------


class PermitChecklistRequest(BaseModel):
    project_id: UUID
    jurisdiction: str
    project_type: str
    parameters: ProjectParameters | None = None


class ChecklistItem(BaseModel):
    id: str
    title: str
    description: str | None = None
    regulation_ref: str | None = None
    required: bool = True
    status: ChecklistItemStatus = ChecklistItemStatus.pending
    assignee_id: UUID | None = None
    notes: str | None = None
    updated_at: datetime | None = None


class PermitChecklist(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None
    jurisdiction: str
    project_type: str
    items: list[ChecklistItem]
    generated_at: datetime
    completed_at: datetime | None = None


class MarkItemRequest(BaseModel):
    item_id: str
    status: ChecklistItemStatus
    notes: str | None = None
    assignee_id: UUID | None = None


# ---------- Compliance check records ----------


class ComplianceCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None
    check_type: CheckType
    status: CheckStatus
    input: dict[str, Any] | None = None
    findings: list[Finding] | None = None
    regulations_referenced: list[UUID] = Field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime
