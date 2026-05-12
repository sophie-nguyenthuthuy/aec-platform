"""Pydantic schemas for THANHTOAN — progress payment claims.

The arithmetic helper `recompute_totals()` is the single source of
truth for VN payment math. Both the API and the test suite call it,
so the numbers in the BBNT match the numbers in the e-invoice match
the numbers in the audit log.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------- Enums ----------


class ClaimStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    paid = "paid"
    cancelled = "cancelled"


class PartyDecision(StrEnum):
    approve = "approve"
    reject = "reject"


class EvidenceKind(StrEnum):
    photo = "photo"
    document = "document"
    invoice = "invoice"
    test_cert = "test_cert"
    dailylog_ref = "dailylog_ref"
    nghiemthu_ref = "nghiemthu_ref"


# Default tax / retention rates. Centralised so a single edit changes
# the platform-wide defaults; per-claim overrides still allowed.
DEFAULT_VAT_PCT = Decimal("0.0800")  # construction services 2024+
DEFAULT_RETENTION_PCT = Decimal("0.0500")  # 5% giữ lại bảo hành
DEFAULT_TNDN_PCT = Decimal("0.0100")  # 1% TNDN tạm thu (TT 80/2021)


# ---------- Money helper ----------


def _round_vnd(value: Decimal) -> int:
    """Round to the nearest đồng (banker's rounding *to* integer VND).

    VN convention is half-up at the đồng — invoices are issued without
    fractional VND, and tax authorities expect the same.
    """
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_totals(
    line_amounts_vnd: list[int],
    vat_pct: Decimal = DEFAULT_VAT_PCT,
    retention_pct: Decimal = DEFAULT_RETENTION_PCT,
    tndn_pct: Decimal = DEFAULT_TNDN_PCT,
) -> dict[str, int | Decimal]:
    """Compute the canonical money totals for a claim.

    Order of operations matters:
      1. subtotal  = Σ lines
      2. vat       = subtotal × vat_pct
      3. gross     = subtotal + vat
      4. retention = gross × retention_pct        (retention is on gross
                                                  of VAT — common
                                                  contractual norm)
      5. tndn      = subtotal × tndn_pct          (TNDN on the pre-VAT
                                                  base, per TT 80/2021)
      6. net       = gross - retention - tndn

    Returns the typed components so callers don't have to re-derive.
    """
    subtotal = Decimal(sum(line_amounts_vnd))
    vat = subtotal * vat_pct
    gross = subtotal + vat
    retention = gross * retention_pct
    tndn = subtotal * tndn_pct
    net = gross - retention - tndn
    return {
        "subtotal_vnd": _round_vnd(subtotal),
        "vat_pct": vat_pct,
        "vat_vnd": _round_vnd(vat),
        "gross_vnd": _round_vnd(gross),
        "retention_pct": retention_pct,
        "retention_vnd": _round_vnd(retention),
        "tndn_pct": tndn_pct,
        "tndn_vnd": _round_vnd(tndn),
        "net_payable_vnd": _round_vnd(net),
    }


# ---------- Lines ----------


class PaymentClaimLineCreate(BaseModel):
    work_item_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=400)
    unit: str = Field(min_length=1, max_length=20)
    planned_qty: Decimal = Field(ge=0)
    this_period_qty: Decimal = Field(ge=0)
    unit_rate_vnd: int = Field(ge=0)
    notes: str | None = None
    evidence_file_ids: list[UUID] = Field(default_factory=list)
    sort_order: int = 0


class PaymentClaimLineUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=400)
    this_period_qty: Decimal | None = Field(default=None, ge=0)
    unit_rate_vnd: int | None = Field(default=None, ge=0)
    notes: str | None = None
    evidence_file_ids: list[UUID] | None = None


class PaymentClaimLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    claim_id: UUID
    work_item_code: str
    description: str
    unit: str
    planned_qty: Decimal
    this_period_qty: Decimal
    cumulative_qty: Decimal
    unit_rate_vnd: int
    this_period_amount_vnd: int
    cumulative_amount_vnd: int
    completion_pct: Decimal | None = None
    notes: str | None = None
    evidence_file_ids: list[UUID] = Field(default_factory=list)
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---------- Claim header ----------


class PaymentClaimCreate(BaseModel):
    project_id: UUID
    claim_no: str = Field(min_length=1, max_length=64)
    period_start: date
    period_end: date
    vat_pct: Decimal = DEFAULT_VAT_PCT
    retention_pct: Decimal = DEFAULT_RETENTION_PCT
    tndn_pct: Decimal = DEFAULT_TNDN_PCT
    due_at: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _period_order(self) -> PaymentClaimCreate:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be >= period_start")
        return self


class PaymentClaimUpdate(BaseModel):
    period_start: date | None = None
    period_end: date | None = None
    vat_pct: Decimal | None = None
    retention_pct: Decimal | None = None
    tndn_pct: Decimal | None = None
    due_at: date | None = None
    notes: str | None = None


class PaymentClaim(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    claim_no: str
    sequence: int
    period_start: date
    period_end: date
    status: ClaimStatus
    subtotal_vnd: int
    vat_pct: Decimal
    vat_vnd: int
    gross_vnd: int
    retention_pct: Decimal
    retention_vnd: int
    tndn_pct: Decimal
    tndn_vnd: int
    net_payable_vnd: int
    cumulative_prev_vnd: int
    submitted_at: datetime | None = None
    cdt_signed_at: datetime | None = None
    cdt_signed_by: UUID | None = None
    cdt_decision: str | None = None
    cdt_comment: str | None = None
    tvgs_signed_at: datetime | None = None
    tvgs_signed_by: UUID | None = None
    tvgs_decision: str | None = None
    tvgs_comment: str | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    due_at: date | None = None
    paid_at: date | None = None
    payment_reference: str | None = None
    pdf_file_id: UUID | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ClaimListFilters(BaseModel):
    project_id: UUID | None = None
    status: ClaimStatus | None = None
    period_year: int | None = Field(default=None, ge=2000, le=2100)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ClaimSummary(BaseModel):
    """List-card view."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    claim_no: str
    sequence: int
    period_start: date
    period_end: date
    status: ClaimStatus
    net_payable_vnd: int
    line_count: int
    due_at: date | None = None
    paid_at: date | None = None
    created_at: datetime


# ---------- Workflow payloads ----------


class SubmitPayload(BaseModel):
    """No body needed — kept as an explicit model so the OpenAPI shape
    matches `/sign` and `/mark-paid` (every workflow op POSTs JSON)."""

    notes: str | None = None


class SignPayload(BaseModel):
    role: str  # `cdt` | `tvgs`
    decision: PartyDecision
    comment: str | None = None


class MarkPaidPayload(BaseModel):
    paid_at: date
    payment_reference: str | None = None


# ---------- Evidence ----------


class EvidenceCreate(BaseModel):
    kind: EvidenceKind
    file_id: UUID | None = None
    external_ref: str | None = None
    caption: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class PaymentClaimEvidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    claim_id: UUID
    kind: EvidenceKind
    file_id: UUID | None = None
    external_ref: str | None = None
    caption: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    sort_order: int
    created_at: datetime


# ---------- Detail ----------


class PaymentClaimDetail(PaymentClaim):
    lines: list[PaymentClaimLine] = Field(default_factory=list)
    evidence: list[PaymentClaimEvidence] = Field(default_factory=list)


# ---------- Cumulative-across-periods ----------


class CumulativeRow(BaseModel):
    """One row in the per-work-item running total table."""

    work_item_code: str
    description: str
    unit: str
    planned_qty: Decimal
    cumulative_qty: Decimal
    cumulative_amount_vnd: int
    completion_pct: Decimal | None = None


class CumulativeView(BaseModel):
    claim_id: UUID
    project_id: UUID
    rows: list[CumulativeRow]
    grand_total_vnd: int
