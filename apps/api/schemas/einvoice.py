"""Pydantic schemas for EINVOICE — Vietnamese e-invoice."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------- Enums ----------


class InvoiceDirection(StrEnum):
    issued = "issued"
    received = "received"


class InvoiceStatus(StrEnum):
    draft = "draft"
    issued = "issued"
    submitted_gdt = "submitted_gdt"
    accepted_gdt = "accepted_gdt"
    rejected_gdt = "rejected_gdt"
    cancelled = "cancelled"
    adjustment_issued = "adjustment_issued"


class GdtStatus(StrEnum):
    active = "active"
    suspended = "suspended"
    closed = "closed"
    not_found = "not_found"


# Standard VAT rates — kept as Decimal so the arithmetic doesn't drift.
class VatRate:
    EXPORT = Decimal("0.00")
    ESSENTIAL = Decimal("0.05")
    REDUCED = Decimal("0.08")  # 2024-2025 reduced rate for construction etc.
    STANDARD = Decimal("0.10")


VALID_VAT_RATES: frozenset[Decimal] = frozenset(
    {VatRate.EXPORT, VatRate.ESSENTIAL, VatRate.REDUCED, VatRate.STANDARD}
)


# ---------- MST validation ----------


_MST_RE = re.compile(r"^\d{10}(-\d{3})?$")


def validate_mst(value: str) -> str:
    """Validate the shape of a VN Mã số thuế.

    10 digits (head office) or 10-3 form (10 digits + dash + 3 digits
    for branches). Surface format errors as ValueError so Pydantic
    turns them into 422.
    """
    if not _MST_RE.match(value or ""):
        raise ValueError(f"invalid MST format: {value!r}")
    return value


# ---------- Money helpers ----------


def _round_vnd(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_line(qty: Decimal, unit_price: int, discount_pct: Decimal, vat_rate: Decimal | None) -> tuple[int, int]:
    """Return (line_total, vat_amount) for a line.

    `discount_pct` is a Decimal fraction (0.10 = 10% off).
    `vat_rate` None → exempt → vat_amount = 0.
    """
    gross = Decimal(qty) * Decimal(unit_price)
    line_total = gross * (Decimal("1") - Decimal(discount_pct or 0))
    line_total_int = _round_vnd(line_total)
    if vat_rate is None:
        return line_total_int, 0
    vat = Decimal(line_total_int) * Decimal(vat_rate)
    return line_total_int, _round_vnd(vat)


def build_vat_breakdown(lines: list[tuple[int, int, Decimal | None]]) -> list[dict[str, Any]]:
    """Group lines by VAT rate → breakdown rows for the HĐĐT form.

    `lines` is a list of (line_total, vat_amount, vat_rate). Returns
    sorted rows by descending rate (the legal display order).
    """
    buckets: dict[str | None, dict[str, Any]] = {}
    for line_total, vat_amount, rate in lines:
        key = str(rate) if rate is not None else None
        b = buckets.setdefault(
            key,
            {
                "rate": float(rate) if rate is not None else None,
                "base": 0,
                "vat_amount": 0,
                "description": _rate_label(rate),
            },
        )
        b["base"] += int(line_total)
        b["vat_amount"] += int(vat_amount)
    # Sort: rate desc, exempt (None) last. Tuple key puts non-null
    # rows first (False < True) and then orders them by descending
    # rate within their group.
    return sorted(
        buckets.values(),
        key=lambda b: (b["rate"] is None, -float(b["rate"]) if b["rate"] is not None else 0.0),
    )


def _rate_label(rate: Decimal | None) -> str:
    if rate is None:
        return "Không chịu thuế GTGT"
    pct = int(rate * 100)
    return f"Thuế GTGT {pct}%"


# ---------- Lines ----------


class EInvoiceLineCreate(BaseModel):
    sort_order: int = 0
    description: str = Field(min_length=1, max_length=400)
    item_code: str | None = None
    unit: str = Field(default="cái", min_length=1, max_length=20)
    qty: Decimal = Field(ge=0)
    unit_price: int = Field(ge=0)
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1"))
    vat_rate: Decimal | None = None

    @field_validator("vat_rate")
    @classmethod
    def _vat_rate_must_be_known(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return v
        if v not in VALID_VAT_RATES:
            raise ValueError(
                f"vat_rate must be one of {{None, 0, 0.05, 0.08, 0.10}}, got {v}"
            )
        return v


class EInvoiceLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    invoice_id: UUID
    sort_order: int
    description: str
    item_code: str | None = None
    unit: str
    qty: Decimal
    unit_price: int
    discount_pct: Decimal
    line_total: int
    vat_rate: Decimal | None = None
    vat_amount: int
    created_at: datetime


# ---------- Invoice header ----------


class EInvoiceCreate(BaseModel):
    project_id: UUID | None = None
    direction: InvoiceDirection
    invoice_no: str = Field(min_length=1, max_length=20)
    template_no: str = Field(min_length=1, max_length=20)
    serial_no: str = Field(min_length=1, max_length=20)
    issue_date: date
    due_date: date | None = None
    issuer_mst: str
    issuer_name: str = Field(min_length=1, max_length=400)
    issuer_address: str | None = None
    issuer_bank_account: str | None = None
    buyer_mst: str | None = None
    buyer_name: str = Field(min_length=1, max_length=400)
    buyer_address: str | None = None
    buyer_email: str | None = None
    currency: str = Field(default="VND", min_length=3, max_length=3)
    exchange_rate: Decimal = Field(default=Decimal("1"), gt=0)
    payment_method: str | None = None
    payment_reference: str | None = None
    notes: str | None = None
    lines: list[EInvoiceLineCreate] = Field(default_factory=list)

    @field_validator("issuer_mst")
    @classmethod
    def _v_issuer_mst(cls, v: str) -> str:
        return validate_mst(v)

    @field_validator("buyer_mst")
    @classmethod
    def _v_buyer_mst(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        return validate_mst(v)


class EInvoiceUpdate(BaseModel):
    issue_date: date | None = None
    due_date: date | None = None
    buyer_mst: str | None = None
    buyer_name: str | None = Field(default=None, min_length=1, max_length=400)
    buyer_address: str | None = None
    buyer_email: str | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    notes: str | None = None

    @field_validator("buyer_mst")
    @classmethod
    def _v_buyer_mst(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        return validate_mst(v)


class EInvoice(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID | None = None
    direction: InvoiceDirection
    invoice_no: str
    template_no: str
    serial_no: str
    status: InvoiceStatus
    issuer_mst: str
    issuer_name: str
    issuer_address: str | None = None
    issuer_bank_account: str | None = None
    buyer_mst: str | None = None
    buyer_name: str
    buyer_address: str | None = None
    buyer_email: str | None = None
    issue_date: date
    due_date: date | None = None
    paid_at: date | None = None
    currency: str
    exchange_rate: Decimal
    subtotal: int
    vat_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    vat_total: int
    total: int
    gdt_code: str | None = None
    gdt_submitted_at: datetime | None = None
    gdt_accepted_at: datetime | None = None
    gdt_rejection_reason: str | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    adjustment_for_id: UUID | None = None
    adjustment_reason: str | None = None
    xml_file_id: UUID | None = None
    pdf_file_id: UUID | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class InvoiceListFilters(BaseModel):
    project_id: UUID | None = None
    direction: InvoiceDirection | None = None
    status: InvoiceStatus | None = None
    buyer_mst: str | None = None
    issuer_mst: str | None = None
    issued_year: int | None = Field(default=None, ge=2000, le=2100)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class InvoiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None = None
    direction: InvoiceDirection
    invoice_no: str
    template_no: str
    serial_no: str
    status: InvoiceStatus
    issuer_mst: str
    issuer_name: str
    buyer_mst: str | None = None
    buyer_name: str
    issue_date: date
    due_date: date | None = None
    paid_at: date | None = None
    total: int
    line_count: int
    gdt_code: str | None = None
    created_at: datetime


class InvoiceDetail(EInvoice):
    lines: list[EInvoiceLine] = Field(default_factory=list)


# ---------- Workflow ----------


class IssueInvoicePayload(BaseModel):
    """Optional cover-note when finalizing an invoice."""

    note: str | None = None


class CancelInvoicePayload(BaseModel):
    reason: str = Field(min_length=1, max_length=400)
    replacement_invoice_id: UUID | None = None


class SubmitGdtPayload(BaseModel):
    """Stub payload — real impl would attach signed XML."""

    xml_file_id: UUID | None = None


class GdtCallback(BaseModel):
    """Callback shape from the GDT e-invoice service.

    Surfaced as its own POST endpoint so the service can deliver
    accept/reject decisions asynchronously.
    """

    gdt_code: str | None = None
    accepted: bool
    rejection_reason: str | None = None


# ---------- MST validation ----------


class MstValidateRequest(BaseModel):
    mst: str

    @field_validator("mst")
    @classmethod
    def _v_mst(cls, v: str) -> str:
        return validate_mst(v)


class MstInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    mst: str
    gdt_status: GdtStatus
    legal_name: str | None = None
    address: str | None = None
    registered_at: date | None = None
    business_type: str | None = None
    last_checked_at: datetime
