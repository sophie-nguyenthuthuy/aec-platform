"""Pydantic schemas for NGHIEMTHU — statutory acceptance forms.

Enums anchor to the NĐ 06/2021/NĐ-CP vocabulary so the API speaks the
same language as the regulator and the on-site QA team.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class AcceptanceLevel(StrEnum):
    """Three statutory levels — NĐ 06/2021 Art. 9, 11, 13."""

    cong_viec = "cong_viec"  # work-task acceptance (daily / per item)
    giai_doan = "giai_doan"  # stage / phase acceptance
    hoan_thanh = "hoan_thanh"  # completion acceptance (occupancy gate)


class AcceptanceStatus(StrEnum):
    draft = "draft"
    in_signoff = "in_signoff"
    accepted = "accepted"
    rejected = "rejected"
    superseded = "superseded"


class SignatoryRole(StrEnum):
    """Statutory parties to a BBNT — NĐ 06/2021 Art. 11.

    The first three (CĐT, TVGS, NT) are always mandatory. TVTK and
    TVQLDA only when the contract assigns them.
    """

    cdt = "cdt"  # Chủ đầu tư (owner / investor)
    tvgs = "tvgs"  # Tư vấn giám sát (construction supervision)
    nt = "nt"  # Nhà thầu (contractor)
    tvtk = "tvtk"  # Tư vấn thiết kế (design consultant)
    tvqlda = "tvqlda"  # Tư vấn quản lý dự án (PM consultant)


class SignatoryDecision(StrEnum):
    pending = "pending"
    approve = "approve"
    reject = "reject"
    comment_only = "comment_only"


class EvidenceKind(StrEnum):
    photo = "photo"
    document = "document"
    test_cert = "test_cert"
    drawing_ref = "drawing_ref"
    dailylog_ref = "dailylog_ref"
    task_ref = "task_ref"


# Roles that must approve before a BBNT can finalize.
MANDATORY_ROLES: frozenset[SignatoryRole] = frozenset(
    {SignatoryRole.cdt, SignatoryRole.tvgs, SignatoryRole.nt}
)


# ---------- Quantity row (typed item inside the JSONB column) ----------


class QuantityRow(BaseModel):
    """One row of the measured-quantities table on the BBNT.

    Variance is reader-computed so a stale variance doesn't lie when
    the planned / actual values are edited.
    """

    code: str
    name: str
    unit: str
    planned: float
    actual: float
    note: str | None = None

    @property
    def variance_pct(self) -> float:
        if self.planned == 0:
            return 0.0
        return ((self.actual - self.planned) / self.planned) * 100.0


# ---------- Records ----------


class AcceptanceRecordCreate(BaseModel):
    project_id: UUID
    reference_no: str = Field(min_length=1, max_length=64)
    acceptance_level: AcceptanceLevel
    title: str = Field(min_length=1, max_length=400)
    acceptance_date: date
    location: str | None = None
    work_item_codes: list[str] = Field(default_factory=list)
    quantities: list[QuantityRow] = Field(default_factory=list)
    basis: dict[str, Any] = Field(default_factory=dict)
    conclusion: str | None = None


class AcceptanceRecordUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=400)
    acceptance_date: date | None = None
    location: str | None = None
    work_item_codes: list[str] | None = None
    quantities: list[QuantityRow] | None = None
    basis: dict[str, Any] | None = None
    conclusion: str | None = None


class AcceptanceRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    reference_no: str
    acceptance_level: AcceptanceLevel
    title: str
    status: AcceptanceStatus
    acceptance_date: date
    location: str | None = None
    work_item_codes: list[str] = Field(default_factory=list)
    quantities: list[dict[str, Any]] = Field(default_factory=list)
    basis: dict[str, Any] = Field(default_factory=dict)
    conclusion: str | None = None
    pdf_file_id: UUID | None = None
    superseded_by_id: UUID | None = None
    finalized_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class RecordListFilters(BaseModel):
    project_id: UUID | None = None
    acceptance_level: AcceptanceLevel | None = None
    status: AcceptanceStatus | None = None
    work_item_code: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RecordSummary(BaseModel):
    """List-card view with signoff progress."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    reference_no: str
    acceptance_level: AcceptanceLevel
    title: str
    status: AcceptanceStatus
    acceptance_date: date
    signatories_total: int = 0
    signatories_signed: int = 0
    mandatory_pending: int = 0
    finalized_at: datetime | None = None
    created_at: datetime


# ---------- Signatories ----------


class SignatoryCreate(BaseModel):
    role: SignatoryRole
    org_name: str = Field(min_length=1, max_length=200)
    representative_name: str = Field(min_length=1, max_length=200)
    position: str | None = None
    required: bool = True
    sort_order: int = 0


class SignatorySign(BaseModel):
    """Payload for signing a signatory row.

    `signed_at` defaults to NOW() at the DB if omitted, so callers
    using an out-of-band signature service can backdate to the actual
    signing moment.
    """

    decision: SignatoryDecision
    comment: str | None = None
    signed_at: datetime | None = None
    signature_file_id: UUID | None = None


class AcceptanceSignatory(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    record_id: UUID
    role: SignatoryRole
    org_name: str
    representative_name: str
    position: str | None = None
    required: bool
    decision: SignatoryDecision
    comment: str | None = None
    signed_at: datetime | None = None
    signature_file_id: UUID | None = None
    signed_by_user_id: UUID | None = None
    sort_order: int
    created_at: datetime


# ---------- Evidence ----------


class EvidenceCreate(BaseModel):
    kind: EvidenceKind
    file_id: UUID | None = None
    external_ref: str | None = None
    caption: str | None = None
    captured_at: datetime | None = None
    sort_order: int = 0


class AcceptanceEvidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    record_id: UUID
    kind: EvidenceKind
    file_id: UUID | None = None
    external_ref: str | None = None
    caption: str | None = None
    captured_at: datetime | None = None
    sort_order: int
    created_at: datetime


# ---------- Detail / finalize ----------


class AcceptanceDetail(AcceptanceRecord):
    signatories: list[AcceptanceSignatory] = Field(default_factory=list)
    evidence: list[AcceptanceEvidence] = Field(default_factory=list)


class FinalizeResult(BaseModel):
    record_id: UUID
    status: AcceptanceStatus
    mandatory_pending_roles: list[SignatoryRole] = Field(default_factory=list)
    rejected_by_roles: list[SignatoryRole] = Field(default_factory=list)
    message: str
