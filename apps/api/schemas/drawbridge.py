"""Pydantic schemas for DRAWBRIDGE module."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- Enums ----------

class Discipline(str, Enum):
    architectural = "architectural"
    structural = "structural"
    mep = "mep"
    civil = "civil"


class DocType(str, Enum):
    drawing = "drawing"
    spec = "spec"
    report = "report"
    contract = "contract"
    rfi = "rfi"
    submittal = "submittal"


class ProcessingStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class ChunkType(str, Enum):
    text = "text"
    table = "table"
    schedule = "schedule"
    note = "note"
    dimension = "dimension"


class ConflictStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class ConflictSeverity(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"


class ConflictType(str, Enum):
    dimension = "dimension"
    material = "material"
    structural = "structural"
    elevation = "elevation"


class RfiStatus(str, Enum):
    open = "open"
    answered = "answered"
    closed = "closed"


class RfiPriority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


# ---------- Document sets ----------

class DocumentSetBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    discipline: Discipline | None = None
    revision: str | None = None
    issued_date: date | None = None


class DocumentSetCreate(DocumentSetBase):
    project_id: UUID


class DocumentSet(DocumentSetBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None
    organization_id: UUID
    created_at: datetime


# ---------- Documents ----------

class DocumentBase(BaseModel):
    doc_type: DocType | None = None
    drawing_number: str | None = None
    title: str | None = None
    revision: str | None = None
    discipline: Discipline | None = None
    scale: str | None = None


class DocumentUpload(BaseModel):
    """Metadata passed alongside a multipart file upload."""
    project_id: UUID
    document_set_id: UUID | None = None
    doc_type: DocType | None = None
    drawing_number: str | None = None
    title: str | None = None
    revision: str | None = None
    discipline: Discipline | None = None
    scale: str | None = None


class Document(DocumentBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    document_set_id: UUID | None
    file_id: UUID | None
    processing_status: ProcessingStatus
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    created_at: datetime


class DocumentListFilters(BaseModel):
    project_id: UUID | None = None
    document_set_id: UUID | None = None
    discipline: Discipline | None = None
    doc_type: DocType | None = None
    processing_status: ProcessingStatus | None = None
    q: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ---------- Document Q&A ----------

class SourceDocument(BaseModel):
    document_id: UUID
    drawing_number: str | None = None
    title: str | None = None
    discipline: Discipline | None = None
    page: int | None = None
    excerpt: str
    bbox: dict[str, Any] | None = None


class QueryRequest(BaseModel):
    project_id: UUID
    question: str = Field(min_length=3, max_length=2000)
    disciplines: list[Discipline] | None = None
    document_ids: list[UUID] | None = None
    top_k: int = Field(default=12, ge=1, le=30)
    language: Literal["vi", "en"] | None = None


class QueryResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_documents: list[SourceDocument] = Field(default_factory=list)
    related_questions: list[str] = Field(default_factory=list)


# ---------- Conflict detection ----------

class ConflictScanRequest(BaseModel):
    project_id: UUID
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Restrict scan to these documents. If omitted, scans all ready drawings.",
    )
    severities: list[ConflictSeverity] | None = None


class ConflictExcerpt(BaseModel):
    document_id: UUID
    drawing_number: str | None = None
    discipline: Discipline | None = None
    page: int | None = None
    excerpt: str
    bbox: dict[str, Any] | None = None


class ConflictBase(BaseModel):
    severity: ConflictSeverity | None = None
    conflict_type: ConflictType | None = None
    description: str | None = None
    ai_explanation: str | None = None


class Conflict(ConflictBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    status: ConflictStatus
    document_a_id: UUID | None
    chunk_a_id: UUID | None
    document_b_id: UUID | None
    chunk_b_id: UUID | None
    resolution_notes: str | None = None
    detected_at: datetime
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None


class ConflictWithExcerpts(Conflict):
    document_a: ConflictExcerpt | None = None
    document_b: ConflictExcerpt | None = None


class ConflictUpdate(BaseModel):
    status: Literal["open", "resolved", "dismissed"] | None = None
    resolution_notes: str | None = None


class ConflictScanResponse(BaseModel):
    project_id: UUID
    scanned_documents: int
    candidates_evaluated: int
    conflicts_found: int
    conflicts: list[Conflict]


class ConflictListFilters(BaseModel):
    project_id: UUID
    status: ConflictStatus | None = None
    severity: ConflictSeverity | None = None
    conflict_type: ConflictType | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ---------- Schedule / data extraction ----------

class ExtractRequest(BaseModel):
    document_id: UUID
    target: Literal["schedule", "dimensions", "materials", "title_block", "all"] = "schedule"
    pages: list[int] | None = None


class ScheduleRow(BaseModel):
    cells: dict[str, Any]


class ExtractedSchedule(BaseModel):
    name: str
    page: int | None = None
    columns: list[str]
    rows: list[ScheduleRow]


class ExtractedDimension(BaseModel):
    label: str
    value_mm: float | None = None
    raw: str
    page: int | None = None
    bbox: dict[str, Any] | None = None


class ExtractedMaterial(BaseModel):
    code: str | None = None
    description: str
    quantity: float | None = None
    unit: str | None = None
    page: int | None = None


class ExtractResponse(BaseModel):
    document_id: UUID
    schedules: list[ExtractedSchedule] = Field(default_factory=list)
    dimensions: list[ExtractedDimension] = Field(default_factory=list)
    materials: list[ExtractedMaterial] = Field(default_factory=list)
    title_block: dict[str, Any] | None = None


# ---------- RFIs ----------

class RfiBase(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    description: str | None = None
    priority: RfiPriority = RfiPriority.normal
    due_date: date | None = None
    related_document_ids: list[UUID] = Field(default_factory=list)
    assigned_to: UUID | None = None
    number: str | None = None


class RfiCreate(RfiBase):
    project_id: UUID


class RfiUpdate(BaseModel):
    subject: str | None = None
    description: str | None = None
    status: RfiStatus | None = None
    priority: RfiPriority | None = None
    due_date: date | None = None
    assigned_to: UUID | None = None
    related_document_ids: list[UUID] | None = None


class RfiAnswer(BaseModel):
    response: str = Field(min_length=1)
    close: bool = True


class Rfi(RfiBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    status: RfiStatus
    response: str | None = None
    raised_by: UUID | None = None
    created_at: datetime


class RfiListFilters(BaseModel):
    project_id: UUID
    status: RfiStatus | None = None
    assigned_to: UUID | None = None
    priority: RfiPriority | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class RfiGenerateFromConflictRequest(BaseModel):
    conflict_id: UUID
    assigned_to: UUID | None = None
    due_date: date | None = None
    priority: RfiPriority = RfiPriority.high


class RfiDraft(BaseModel):
    subject: str
    description: str
    related_document_ids: list[UUID] = Field(default_factory=list)
    priority: RfiPriority = RfiPriority.high
