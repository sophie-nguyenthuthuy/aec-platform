"""Pydantic schemas for PERMITFLOW.

Enums encode VN-specific vocabulary (cấp công trình, ministry codes,
NĐ legal basis) so they stay typed end-to-end rather than free strings.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------- Enums ----------


class ProjectClassification(StrEnum):
    """Cấp công trình per QCVN 03:2022/BXD.

    Drives which authority appraises the basic design (TKCS): grade I /
    special go through BXD central; grade II-III stay at SXD provincial;
    grade IV is exempt from TKCS appraisal but still needs GPXD.
    """

    cap_iv = "cap_iv"
    cap_iii = "cap_iii"
    cap_ii = "cap_ii"
    cap_i = "cap_i"
    dac_biet = "dac_biet"


class InvestmentType(StrEnum):
    domestic = "domestic"
    fdi = "fdi"


class DossierStatus(StrEnum):
    planning = "planning"
    in_progress = "in_progress"
    on_hold = "on_hold"
    completed = "completed"
    cancelled = "cancelled"


class StageCode(StrEnum):
    """The 5 canonical stages, in submission order."""

    chu_truong_dau_tu = "chu_truong_dau_tu"
    quy_hoach_1_500 = "quy_hoach_1_500"
    tham_dinh_tkcs = "tham_dinh_tkcs"
    gpxd = "gpxd"
    nghiem_thu_pccc = "nghiem_thu_pccc"


# Canonical ordering used to seed stages + enforce the "no skip" rule.
STAGE_ORDER: tuple[StageCode, ...] = (
    StageCode.chu_truong_dau_tu,
    StageCode.quy_hoach_1_500,
    StageCode.tham_dinh_tkcs,
    StageCode.gpxd,
    StageCode.nghiem_thu_pccc,
)


class Authority(StrEnum):
    """Issuing authorities. Codes mirror common Vietnamese abbreviations."""

    BKHDT = "BKHDT"  # Bộ Kế hoạch và Đầu tư
    BXD = "BXD"  # Bộ Xây dựng
    UBND_TINH = "UBND_TINH"  # Ủy ban Nhân dân Tỉnh / Thành phố
    UBND_HUYEN = "UBND_HUYEN"  # Ủy ban Nhân dân Huyện / Quận
    SXD = "SXD"  # Sở Xây dựng
    PC07 = "PC07"  # Phòng Cảnh sát PCCC


class StageStatus(StrEnum):
    not_started = "not_started"
    preparing = "preparing"
    submitted = "submitted"
    in_review = "in_review"
    rfi = "rfi"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"
    expired = "expired"


class SubmissionType(StrEnum):
    initial = "initial"
    rfi_response = "rfi_response"
    resubmission = "resubmission"
    withdrawal_request = "withdrawal_request"


class SubmissionOutcome(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rfi_issued = "rfi_issued"
    rejected = "rejected"


# ---------- Helpers (authority + legal basis derivation) ----------


def default_authority(
    stage: StageCode,
    classification: ProjectClassification,
    investment_type: InvestmentType,
) -> Authority:
    """Pick the authority for a stage given project shape.

    Captures the most-common routing per VN practice; users can override
    on the stage row when local conditions differ (e.g. SXD vs UBND
    delegation by district).
    """
    if stage == StageCode.chu_truong_dau_tu:
        return Authority.BKHDT if investment_type == InvestmentType.fdi else Authority.UBND_TINH
    if stage == StageCode.quy_hoach_1_500:
        return Authority.UBND_TINH
    if stage == StageCode.tham_dinh_tkcs:
        # Grade I / special → BXD; grade II-III → SXD; grade IV exempt
        # (we still seed a stage at SXD as a no-op marker).
        if classification in (ProjectClassification.cap_i, ProjectClassification.dac_biet):
            return Authority.BXD
        return Authority.SXD
    if stage == StageCode.gpxd:
        # Most GPXD issuance sits with SXD, but UBND huyện handles
        # individual housing / cấp IV. Default to SXD.
        return Authority.UBND_HUYEN if classification == ProjectClassification.cap_iv else Authority.SXD
    if stage == StageCode.nghiem_thu_pccc:
        return Authority.PC07
    raise ValueError(f"unknown stage: {stage}")


def default_legal_basis(stage: StageCode) -> list[str]:
    """Decrees / laws each stage anchors to.

    Surfaced in the UI as compliance badges and on submission cover
    sheets. The strings are stable codes (not user-facing); the web
    layer maps them to Vietnamese display labels.
    """
    if stage == StageCode.chu_truong_dau_tu:
        return ["luat_dau_tu_2020", "nghi_dinh_31_2021"]
    if stage == StageCode.quy_hoach_1_500:
        return ["luat_quy_hoach_do_thi_2009", "nghi_dinh_37_2010"]
    if stage == StageCode.tham_dinh_tkcs:
        return ["luat_xay_dung_2014_2020", "nghi_dinh_15_2021"]
    if stage == StageCode.gpxd:
        return ["luat_xay_dung_2014_2020", "nghi_dinh_15_2021"]
    if stage == StageCode.nghiem_thu_pccc:
        return ["nghi_dinh_136_2020", "qcvn_06_2022"]
    return []


# ---------- Dossier I/O ----------


class PermitDossierCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    classification: ProjectClassification
    investment_type: InvestmentType = InvestmentType.domestic
    location: dict[str, Any] = Field(default_factory=dict)
    land_cert_file_id: UUID | None = None
    land_parcel_no: str | None = None
    notes: str | None = None


class PermitDossierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    classification: ProjectClassification | None = None
    investment_type: InvestmentType | None = None
    status: DossierStatus | None = None
    location: dict[str, Any] | None = None
    land_cert_file_id: UUID | None = None
    land_parcel_no: str | None = None
    notes: str | None = None


class PermitDossier(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    classification: ProjectClassification
    investment_type: InvestmentType
    status: DossierStatus
    location: dict[str, Any] = Field(default_factory=dict)
    land_cert_file_id: UUID | None = None
    land_parcel_no: str | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class DossierListFilters(BaseModel):
    project_id: UUID | None = None
    status: DossierStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class DossierSummary(BaseModel):
    """Card-friendly summary with stage rollups."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    classification: ProjectClassification
    investment_type: InvestmentType
    status: DossierStatus
    stages_total: int
    stages_approved: int
    next_stage_code: StageCode | None = None
    next_stage_status: StageStatus | None = None
    nearest_expiry: date | None = None
    created_at: datetime


# ---------- Stage I/O ----------


class PermitStage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    dossier_id: UUID
    stage_code: StageCode
    sequence: int
    authority: Authority
    status: StageStatus
    legal_basis: list[str] = Field(default_factory=list)
    target_submit_date: date | None = None
    submitted_date: date | None = None
    decision_date: date | None = None
    decision_number: str | None = None
    decision_file_id: UUID | None = None
    expiry_date: date | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class StageUpdate(BaseModel):
    """Partial update for stage metadata. Use the dedicated transition
    endpoint for status changes that need legality gates (e.g. approve
    requires a prior `in_review`)."""

    authority: Authority | None = None
    target_submit_date: date | None = None
    submitted_date: date | None = None
    decision_date: date | None = None
    decision_number: str | None = None
    decision_file_id: UUID | None = None
    expiry_date: date | None = None
    legal_basis: list[str] | None = None
    notes: str | None = None


class StageTransition(BaseModel):
    """Move a stage to a new status. The router validates the source/target
    pair against an explicit transition matrix; invalid pairs return 422."""

    to_status: StageStatus
    decision_number: str | None = None
    decision_date: date | None = None
    decision_file_id: UUID | None = None
    expiry_date: date | None = None
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _approved_requires_decision(self) -> StageTransition:
        if self.to_status == StageStatus.approved and not (self.decision_date and self.decision_number):
            raise ValueError("approval requires decision_number and decision_date")
        if self.to_status == StageStatus.rejected and not self.rejection_reason:
            raise ValueError("rejection requires rejection_reason")
        return self


# ---------- Submission I/O ----------


class SubmissionCreate(BaseModel):
    submission_type: SubmissionType = SubmissionType.initial
    submitted_at: datetime
    receipt_number: str | None = None
    package_file_ids: list[UUID] = Field(default_factory=list)
    outcome: str | None = None


class SubmissionUpdate(BaseModel):
    outcome: str | None = None
    outcome_status: SubmissionOutcome | None = None
    outcome_at: datetime | None = None


class PermitSubmission(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    stage_id: UUID
    round_number: int
    submission_type: SubmissionType
    submitted_at: datetime
    submitted_by: UUID | None = None
    receipt_number: str | None = None
    package_file_ids: list[UUID] = Field(default_factory=list)
    outcome: str | None = None
    outcome_status: SubmissionOutcome
    outcome_at: datetime | None = None
    created_at: datetime


# ---------- Dossier detail (stages + submissions inline) ----------


class StageWithSubmissions(PermitStage):
    submissions: list[PermitSubmission] = Field(default_factory=list)


class DossierDetail(PermitDossier):
    stages: list[StageWithSubmissions] = Field(default_factory=list)


# ---------- Timeline + alerts ----------


class TimelineEvent(BaseModel):
    occurred_at: datetime
    stage_code: StageCode
    kind: str  # `submission` | `outcome` | `transition`
    description: str
    actor_user_id: UUID | None = None


class DossierTimeline(BaseModel):
    dossier_id: UUID
    events: list[TimelineEvent]


class PermitAlert(BaseModel):
    """Computed alert — not persisted. The cron renders fresh rows each
    morning so resolution of an underlying stage automatically clears
    the alert (no manual ack needed)."""

    dossier_id: UUID
    project_id: UUID
    stage_id: UUID
    stage_code: StageCode
    code: str  # `expiring_soon` | `overdue_submission` | `stalled_review`
    severity: str  # `info` | `warning` | `critical`
    message: str
    expiry_date: date | None = None
    days_until: int | None = None
