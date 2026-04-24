"""Pydantic schemas for HANDOVER module."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- Enums ----------

class PackageStatus(str, Enum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    delivered = "delivered"


class CloseoutCategory(str, Enum):
    drawings = "drawings"
    documents = "documents"
    certificates = "certificates"
    warranties = "warranties"
    manuals = "manuals"
    permits = "permits"
    testing = "testing"
    other = "other"


class CloseoutStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    not_applicable = "not_applicable"


class Discipline(str, Enum):
    architecture = "architecture"
    structure = "structure"
    mep = "mep"
    electrical = "electrical"
    plumbing = "plumbing"
    hvac = "hvac"
    fire = "fire"
    landscape = "landscape"
    interior = "interior"


class OmManualStatus(str, Enum):
    draft = "draft"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class WarrantyStatus(str, Enum):
    active = "active"
    expiring = "expiring"
    expired = "expired"
    claimed = "claimed"


class DefectStatus(str, Enum):
    open = "open"
    assigned = "assigned"
    in_progress = "in_progress"
    resolved = "resolved"
    rejected = "rejected"


class DefectPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# ---------- Packages ----------

class HandoverPackageCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    scope_summary: dict[str, Any] = Field(default_factory=dict)
    auto_populate: bool = Field(
        default=True,
        description="Seed closeout items from project scope when true.",
    )


class HandoverPackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: PackageStatus | None = None
    scope_summary: dict[str, Any] | None = None


class HandoverPackage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    status: PackageStatus
    scope_summary: dict[str, Any] = Field(default_factory=dict)
    export_file_id: UUID | None = None
    delivered_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime


class PackageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    status: PackageStatus
    closeout_total: int = 0
    closeout_done: int = 0
    warranty_expiring: int = 0
    open_defects: int = 0
    delivered_at: datetime | None = None
    created_at: datetime


# ---------- Closeout items ----------

class CloseoutItemCreate(BaseModel):
    category: CloseoutCategory
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    required: bool = True
    sort_order: int = 0


class CloseoutItemUpdate(BaseModel):
    status: CloseoutStatus | None = None
    assignee_id: UUID | None = None
    notes: str | None = None
    file_ids: list[UUID] | None = None


class CloseoutItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    package_id: UUID
    category: CloseoutCategory
    title: str
    description: str | None = None
    required: bool
    status: CloseoutStatus
    assignee_id: UUID | None = None
    file_ids: list[UUID] = Field(default_factory=list)
    notes: str | None = None
    sort_order: int
    updated_at: datetime


class PackageDetail(HandoverPackage):
    closeout_items: list[CloseoutItem] = Field(default_factory=list)


# ---------- As-built drawings ----------

class AsBuiltRegister(BaseModel):
    project_id: UUID
    package_id: UUID | None = None
    drawing_code: str = Field(min_length=1, max_length=100)
    discipline: Discipline
    title: str = Field(min_length=1, max_length=200)
    file_id: UUID
    change_note: str | None = Field(
        default=None,
        description="Description of this version's changes vs. the previous one.",
    )


class AsBuiltChangelogEntry(BaseModel):
    version: int
    file_id: UUID
    change_note: str | None = None
    recorded_at: datetime


class AsBuiltDrawing(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    package_id: UUID | None = None
    drawing_code: str
    discipline: Discipline
    title: str
    current_version: int
    current_file_id: UUID | None = None
    superseded_file_ids: list[UUID] = Field(default_factory=list)
    changelog: list[AsBuiltChangelogEntry] = Field(default_factory=list)
    last_updated_at: datetime


# ---------- O&M manual ----------

class EquipmentSpec(BaseModel):
    tag: str = Field(description="Equipment tag, e.g. 'AHU-01'")
    name: str
    discipline: Discipline
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    location: str | None = None
    capacity: str | None = None
    notes: str | None = None


class MaintenanceTask(BaseModel):
    equipment_tag: str
    task: str
    frequency: str = Field(description="e.g. 'monthly', 'quarterly', 'yearly'")
    duration_minutes: int | None = None
    tools: list[str] = Field(default_factory=list)
    safety: str | None = None


class OmManualGenerateRequest(BaseModel):
    project_id: UUID
    package_id: UUID | None = None
    discipline: Discipline = Discipline.mep
    source_file_ids: list[UUID] = Field(min_length=1, max_length=50)
    title: str | None = None


class OmManual(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    package_id: UUID | None = None
    title: str
    discipline: Discipline
    status: OmManualStatus
    equipment: list[EquipmentSpec] = Field(default_factory=list)
    maintenance_schedule: list[MaintenanceTask] = Field(default_factory=list)
    source_file_ids: list[UUID] = Field(default_factory=list)
    pdf_file_id: UUID | None = None
    ai_job_id: UUID | None = None
    generated_at: datetime
    created_by: UUID | None = None


# ---------- Warranty ----------

class WarrantyExtractRequest(BaseModel):
    project_id: UUID
    package_id: UUID | None = None
    contract_file_ids: list[UUID] = Field(min_length=1, max_length=20)


class WarrantyItemCreate(BaseModel):
    project_id: UUID
    package_id: UUID | None = None
    item_name: str = Field(min_length=1, max_length=200)
    category: str | None = None
    vendor: str | None = None
    contract_file_id: UUID | None = None
    warranty_period_months: int | None = Field(default=None, ge=0, le=600)
    start_date: date | None = None
    expiry_date: date | None = None
    coverage: str | None = None
    claim_contact: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class WarrantyItemUpdate(BaseModel):
    status: WarrantyStatus | None = None
    notes: str | None = None
    claim_contact: dict[str, Any] | None = None


class WarrantyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    package_id: UUID | None = None
    item_name: str
    category: str | None = None
    vendor: str | None = None
    contract_file_id: UUID | None = None
    warranty_period_months: int | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    coverage: str | None = None
    claim_contact: dict[str, Any] = Field(default_factory=dict)
    status: WarrantyStatus
    notes: str | None = None
    days_to_expiry: int | None = None
    created_at: datetime


class WarrantyExtractResponse(BaseModel):
    contract_file_ids: list[UUID]
    extracted_count: int
    items: list[WarrantyItem]


# ---------- Defects ----------

class DefectCreate(BaseModel):
    project_id: UUID
    package_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    location: dict[str, Any] | None = Field(
        default=None,
        description="e.g. { 'room': 'Office 3F-12', 'coords': [x, y] }",
    )
    photo_file_ids: list[UUID] = Field(default_factory=list)
    priority: DefectPriority = DefectPriority.medium
    assignee_id: UUID | None = None


class DefectUpdate(BaseModel):
    status: DefectStatus | None = None
    priority: DefectPriority | None = None
    assignee_id: UUID | None = None
    description: str | None = None
    location: dict[str, Any] | None = None
    photo_file_ids: list[UUID] | None = None
    resolution_notes: str | None = None


class Defect(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    package_id: UUID | None = None
    title: str
    description: str | None = None
    location: dict[str, Any] | None = None
    photo_file_ids: list[UUID] = Field(default_factory=list)
    status: DefectStatus
    priority: DefectPriority
    assignee_id: UUID | None = None
    reported_by: UUID | None = None
    reported_at: datetime
    resolved_at: datetime | None = None
    resolution_notes: str | None = None


# ---------- List filters ----------

class PackageListFilters(BaseModel):
    project_id: UUID | None = None
    status: PackageStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class WarrantyListFilters(BaseModel):
    project_id: UUID | None = None
    package_id: UUID | None = None
    status: WarrantyStatus | None = None
    expiring_within_days: int | None = Field(default=None, ge=0, le=3650)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class DefectListFilters(BaseModel):
    project_id: UUID | None = None
    package_id: UUID | None = None
    status: DefectStatus | None = None
    priority: DefectPriority | None = None
    assignee_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
