"""Pydantic schemas for PCCC — fire-safety certification."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------- Enums ----------


class CertType(StrEnum):
    design = "design"  # thẩm duyệt thiết kế
    acceptance = "acceptance"  # nghiệm thu PCCC
    recert = "recert"  # 5-year renewal of acceptance cert


class HazardCategory(StrEnum):
    """Fire hazard categories per QCVN 06:2022 § 3.

    A = severe explosion (gas, dust), F = minimal hazard (residential).
    Drives almost every downstream rule.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class BuildingClass(StrEnum):
    """Fire resistance class per QCVN 06:2022.

    CO1 = non-combustible (steel + concrete, highest rating);
    CO4 = combustible (heavy timber).
    """

    CO1 = "CO1"
    CO2 = "CO2"
    CO3 = "CO3"
    CO4 = "CO4"


class CertStatus(StrEnum):
    planning = "planning"
    submitted = "submitted"
    inspection_scheduled = "inspection_scheduled"
    rfi = "rfi"
    approved = "approved"
    conditional = "conditional"
    rejected = "rejected"
    expired = "expired"


class InspectionResult(StrEnum):
    passed = "pass"
    conditional_pass = "conditional_pass"
    fail = "fail"
    rescheduled = "rescheduled"


class ChecklistItemStatus(StrEnum):
    pending = "pending"
    compliant = "compliant"
    non_compliant = "non_compliant"
    not_applicable = "not_applicable"


class FindingSeverity(StrEnum):
    """Aligned with the DB CHECK constraint on fire_checklist_items + the
    `medium` server-side default. `medium` is the default for checklist
    items; findings (in inspections) typically use minor/major/critical."""

    info = "info"
    minor = "minor"
    medium = "medium"
    major = "major"
    critical = "critical"


# Cert-type → default legal basis bundle (UI badge mapping lives here).
def default_legal_basis(cert_type: CertType) -> list[str]:
    base = ["nghi_dinh_136_2020", "qcvn_06_2022"]
    if cert_type == CertType.design:
        return [*base, "thong_tu_149_2020_bca"]
    return base


# ---------- Certs ----------


class FireCertCreate(BaseModel):
    project_id: UUID
    cert_type: CertType
    reference_no: str = Field(min_length=1, max_length=64)
    hazard_category: HazardCategory
    building_class: BuildingClass
    height_m: Decimal | None = Field(default=None, ge=0)
    floors_above: int | None = Field(default=None, ge=0)
    floors_below: int | None = Field(default=None, ge=0)
    area_sqm: Decimal | None = Field(default=None, ge=0)
    occupant_load: int | None = Field(default=None, ge=0)
    pc07_unit: str = Field(min_length=1, max_length=64)
    notes: str | None = None


class FireCertUpdate(BaseModel):
    hazard_category: HazardCategory | None = None
    building_class: BuildingClass | None = None
    height_m: Decimal | None = Field(default=None, ge=0)
    floors_above: int | None = Field(default=None, ge=0)
    floors_below: int | None = Field(default=None, ge=0)
    area_sqm: Decimal | None = Field(default=None, ge=0)
    occupant_load: int | None = Field(default=None, ge=0)
    pc07_unit: str | None = Field(default=None, min_length=1, max_length=64)
    submitted_date: date | None = None
    inspection_date: date | None = None
    decision_date: date | None = None
    decision_number: str | None = None
    decision_file_id: UUID | None = None
    expiry_date: date | None = None
    notes: str | None = None


class FireCertTransition(BaseModel):
    """Status change. Cert-type-aware: an acceptance cert flips to
    `expired` automatically when the 5-year mark passes; the API
    rejects manual transition into `expired`."""

    to_status: CertStatus
    decision_date: date | None = None
    decision_number: str | None = None
    decision_file_id: UUID | None = None
    expiry_date: date | None = None
    rejection_reason: str | None = None


class FireCert(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    cert_type: CertType
    reference_no: str
    hazard_category: HazardCategory
    building_class: BuildingClass
    height_m: Decimal | None = None
    floors_above: int | None = None
    floors_below: int | None = None
    area_sqm: Decimal | None = None
    occupant_load: int | None = None
    pc07_unit: str
    status: CertStatus
    submitted_date: date | None = None
    inspection_date: date | None = None
    decision_date: date | None = None
    decision_number: str | None = None
    decision_file_id: UUID | None = None
    expiry_date: date | None = None
    notes: str | None = None
    legal_basis: list[str] = Field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class CertListFilters(BaseModel):
    project_id: UUID | None = None
    cert_type: CertType | None = None
    status: CertStatus | None = None
    expiring_within_days: int | None = Field(default=None, ge=0, le=3650)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CertSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    cert_type: CertType
    reference_no: str
    hazard_category: HazardCategory
    building_class: BuildingClass
    status: CertStatus
    pc07_unit: str
    decision_date: date | None = None
    expiry_date: date | None = None
    checklist_total: int = 0
    checklist_compliant: int = 0
    checklist_non_compliant: int = 0
    inspection_count: int = 0
    created_at: datetime


# ---------- Inspections ----------


class Finding(BaseModel):
    """One line of an inspection report."""

    item: str
    status: ChecklistItemStatus
    severity: FindingSeverity = FindingSeverity.minor
    location: str | None = None
    note: str | None = None
    evidence_file_ids: list[UUID] = Field(default_factory=list)


class InspectionCreate(BaseModel):
    inspection_date: date
    inspector_name: str = Field(min_length=1, max_length=200)
    inspector_org: str | None = None
    overall_result: InspectionResult = InspectionResult.rescheduled
    findings: list[Finding] = Field(default_factory=list)
    summary: str | None = None
    next_steps: str | None = None
    report_file_id: UUID | None = None


class FireInspection(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    cert_id: UUID
    round_number: int
    inspection_date: date
    inspector_name: str
    inspector_org: str | None = None
    overall_result: InspectionResult
    findings: list[dict] = Field(default_factory=list)
    summary: str | None = None
    next_steps: str | None = None
    report_file_id: UUID | None = None
    created_at: datetime


# ---------- Checklist ----------


class ChecklistItemCreate(BaseModel):
    clause_ref: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    severity: FindingSeverity = FindingSeverity.major
    drawing_refs: list[str] = Field(default_factory=list)
    sort_order: int = 0


class ChecklistItemUpdate(BaseModel):
    status: ChecklistItemStatus | None = None
    reviewer_note: str | None = None
    evidence_file_ids: list[UUID] | None = None
    drawing_refs: list[str] | None = None


class ChecklistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    cert_id: UUID
    clause_ref: str
    category: str
    description: str
    status: ChecklistItemStatus
    reviewer_note: str | None = None
    reviewer_user_id: UUID | None = None
    evidence_file_ids: list[UUID] = Field(default_factory=list)
    drawing_refs: list[str] = Field(default_factory=list)
    severity: FindingSeverity
    sort_order: int
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------- Detail + alerts ----------


class CertDetail(FireCert):
    inspections: list[FireInspection] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)


class CertAlert(BaseModel):
    """Computed — surfaces expiring acceptance certs + open non-compliances."""

    cert_id: UUID
    project_id: UUID
    code: str  # `expiring_soon` | `non_compliances_open` | `inspection_overdue`
    severity: str
    message: str
    days_until: int | None = None
    expiry_date: date | None = None


class SeedChecklistRequest(BaseModel):
    """Seed the default QCVN 06:2022 checklist for a cert.

    `template_version` lets us version the seed list — the API picks
    items from a static dict whose keys are (hazard_category,
    building_class). Future revisions of QCVN can add a v2 list
    without breaking historical seeds.
    """

    template_version: str = "qcvn_06_2022_v1"
