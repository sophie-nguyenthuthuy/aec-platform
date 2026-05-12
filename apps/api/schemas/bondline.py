"""Pydantic schemas for BONDLINE — VN bank-issued bonds."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BondType(StrEnum):
    bid = "bid"
    performance = "performance"
    advance = "advance"
    warranty = "warranty"


class BondStatus(StrEnum):
    active = "active"
    released = "released"
    claimed = "claimed"
    expired = "expired"
    cancelled = "cancelled"


class ClaimType(StrEnum):
    default_call = "default_call"
    extension = "extension"
    amount_increase = "amount_increase"
    cancellation = "cancellation"


class ClaimStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    partial = "partial"
    rejected = "rejected"
    withdrawn = "withdrawn"


# VN bank codes accepted out of the box. Adding a bank means an
# alembic migration to extend the CHECK constraint — friction is
# intentional (typo guard).
KNOWN_VN_BANKS: frozenset[str] = frozenset(
    {
        "VCB",  # Vietcombank
        "BIDV",
        "VTB",  # Vietinbank
        "AGB",  # Agribank
        "TCB",  # Techcombank
        "MBB",  # MB Bank
        "ACB",
        "VPB",  # VPBank
        "TPB",  # TPBank
        "STB",  # Sacombank
        "HDB",  # HDBank
        "SHB",
        "OCB",
        "EIB",  # Eximbank
        "MSB",  # Maritime
        "VIB",
        "SCB",
    }
)


# ---------- Bonds ----------


class BondCreate(BaseModel):
    project_id: UUID
    bond_type: BondType
    bond_no: str = Field(min_length=1, max_length=64)
    issuing_bank: str = Field(min_length=2, max_length=10)
    bank_branch: str | None = None
    beneficiary_name: str = Field(min_length=1, max_length=400)
    beneficiary_mst: str | None = None
    face_amount_vnd: int = Field(ge=0)
    contract_value_vnd: int | None = Field(default=None, ge=0)
    coverage_pct: Decimal | None = Field(default=None, ge=0, le=Decimal("1"))
    currency: str = Field(default="VND", min_length=3, max_length=3)
    issue_date: date
    effective_date: date | None = None
    expiry_date: date
    contract_no: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _bank_must_be_known(self) -> BondCreate:
        if self.issuing_bank not in KNOWN_VN_BANKS:
            raise ValueError(f"issuing_bank not in known set: {self.issuing_bank}")
        return self

    @model_validator(mode="after")
    def _expiry_after_issue(self) -> BondCreate:
        if self.expiry_date <= self.issue_date:
            raise ValueError("expiry_date must be after issue_date")
        return self


class BondUpdate(BaseModel):
    bank_branch: str | None = None
    beneficiary_mst: str | None = None
    expiry_date: date | None = None
    contract_no: str | None = None
    notes: str | None = None
    bond_file_id: UUID | None = None


class BondRelease(BaseModel):
    released_at: date
    released_reason: str = Field(min_length=1, max_length=400)


class Bond(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    bond_type: BondType
    bond_no: str
    issuing_bank: str
    bank_branch: str | None = None
    beneficiary_name: str
    beneficiary_mst: str | None = None
    face_amount_vnd: int
    contract_value_vnd: int | None = None
    coverage_pct: Decimal | None = None
    currency: str
    issue_date: date
    effective_date: date | None = None
    expiry_date: date
    status: BondStatus
    released_at: date | None = None
    released_reason: str | None = None
    bond_file_id: UUID | None = None
    contract_no: str | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class BondListFilters(BaseModel):
    project_id: UUID | None = None
    bond_type: BondType | None = None
    status: BondStatus | None = None
    issuing_bank: str | None = None
    expiring_within_days: int | None = Field(default=None, ge=0, le=3650)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class BondSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    bond_type: BondType
    bond_no: str
    issuing_bank: str
    face_amount_vnd: int
    status: BondStatus
    issue_date: date
    expiry_date: date
    days_to_expiry: int | None = None
    claim_count: int = 0
    created_at: datetime


# ---------- Claims ----------


class BondClaimCreate(BaseModel):
    claim_type: ClaimType
    claim_amount_vnd: int | None = Field(default=None, ge=0)
    filed_date: date
    reason: str | None = None
    evidence_file_id: UUID | None = None


class BondClaimDecide(BaseModel):
    status: ClaimStatus
    decided_amount_vnd: int | None = Field(default=None, ge=0)
    decided_date: date
    decision_note: str | None = None


class BondClaim(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    bond_id: UUID
    claim_type: ClaimType
    claim_amount_vnd: int | None = None
    status: ClaimStatus
    filed_date: date
    decided_date: date | None = None
    decided_amount_vnd: int | None = None
    reason: str | None = None
    decision_note: str | None = None
    evidence_file_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime


# ---------- Detail / alerts ----------


class BondDetail(Bond):
    claims: list[BondClaim] = Field(default_factory=list)


class BondAlert(BaseModel):
    bond_id: UUID
    project_id: UUID
    bond_type: BondType
    code: str  # `expiring_soon` | `expired_not_released` | `coverage_below_contract`
    severity: str
    message: str
    days_until: int | None = None
    expiry_date: date | None = None
