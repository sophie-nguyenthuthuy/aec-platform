"""EINVOICE models — Vietnamese e-invoice (Hóa đơn điện tử) per NĐ 123/2020.

The HĐĐT regulatory chain:
  * NĐ 123/2020/NĐ-CP — quy định về hoá đơn, chứng từ
  * TT 78/2021/TT-BTC — hướng dẫn thực hiện NĐ 123/2020
  * QĐ 1450/2021/QĐ-TCT — định dạng dữ liệu HĐĐT (XML schema)

Lifecycle of an HĐĐT in our system:

  draft → issued → submitted_gdt → accepted_gdt
                                ↘─ rejected_gdt → (replace via adjustment_for_id)
  any → cancelled (within 24h of issue, NĐ 123 Art. 19)

`direction = issued` for invoices the org sends; `received` for those
inbound from suppliers (we ingest XML and validate). Both directions
share one table so a "trade payable" view can join across them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class EInvoice(Base):
    """Header for a HĐĐT.

    `template_no` and `serial_no` are the (mẫu hoá đơn / ký hiệu) pair
    issued by the GDT — required on every line item display per TT
    78/2021 Art. 4. Once `gdt_code` is populated (after GDT acceptance)
    the invoice is legally valid; before that it's an internal draft.
    """

    __tablename__ = "einvoices"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    # `issued` (org → buyer) | `received` (org ← supplier)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_no: Mapped[str] = mapped_column(Text, nullable=False)
    template_no: Mapped[str] = mapped_column(Text, nullable=False)  # mẫu hoá đơn
    serial_no: Mapped[str] = mapped_column(Text, nullable=False)  # ký hiệu
    # `draft` | `issued` | `submitted_gdt` | `accepted_gdt` |
    # `rejected_gdt` | `cancelled` | `adjustment_issued`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")

    # ---------- Parties (denormalised at issue time) ----------
    issuer_mst: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_address: Mapped[str | None] = mapped_column(Text)
    issuer_bank_account: Mapped[str | None] = mapped_column(Text)
    buyer_mst: Mapped[str | None] = mapped_column(Text)
    buyer_name: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_address: Mapped[str | None] = mapped_column(Text)
    buyer_email: Mapped[str | None] = mapped_column(Text)

    # ---------- Dates ----------
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[date | None] = mapped_column(Date)

    # ---------- Currency ----------
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="VND")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))

    # ---------- Money totals (in invoice currency, smallest unit) ----------
    subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # JSONB: list of {rate, base, vat_amount, description}. Renders the
    # breakdown table on the BIBN report.
    vat_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    vat_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # ---------- GDT (Tổng cục Thuế) integration ----------
    # Mã CQT — issued by GDT after the e-invoice service accepts the
    # submission. Until populated, the invoice is not legally usable.
    gdt_code: Mapped[str | None] = mapped_column(Text)
    gdt_submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    gdt_accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    gdt_rejection_reason: Mapped[str | None] = mapped_column(Text)

    # ---------- Payment metadata ----------
    payment_method: Mapped[str | None] = mapped_column(Text)
    payment_reference: Mapped[str | None] = mapped_column(Text)

    # Replacement chain — for adjustment / cancellation flows (Art. 19).
    adjustment_for_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("einvoices.id", ondelete="SET NULL")
    )
    adjustment_reason: Mapped[str | None] = mapped_column(Text)

    # File pointers — signed XML (legally authoritative) + display PDF.
    xml_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    pdf_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))

    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        # An (issuer, template, serial, invoice_no) tuple is unique
        # platform-wide once issued — the GDT enforces the same, we
        # mirror it locally so duplicates fail fast.
        UniqueConstraint(
            "issuer_mst",
            "template_no",
            "serial_no",
            "invoice_no",
            name="uq_einvoices_issuer_template_serial_no",
        ),
    )


class EInvoiceLine(Base):
    """Line item on an HĐĐT.

    `vat_rate` uses NUMERIC(5,4) to support 0/5/8/10% standard rates
    plus the "VAT exempt" marker (NULL) — `vat_rate IS NULL` means
    "không chịu thuế GTGT" (NĐ 209/2013), distinct from 0% which is
    "thuế suất 0%" (exports).
    """

    __tablename__ = "einvoice_lines"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("einvoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    item_code: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text, nullable=False, default="cái")
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    unit_price: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    line_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # NULL = exempt; 0/0.05/0.08/0.10 for the four standard rates.
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    vat_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class TaxIdValidation(Base):
    """Cached MST (Mã số thuế) validation result.

    The GDT lookup endpoint is slow and rate-limited, so we cache per
    MST + last_checked_at. Application logic decides whether the cache
    is fresh enough (default: 24h for AAAA-active, 1h for suspended).

    Marked global (no organization_id) intentionally — MST status is
    public information and sharing the cache across tenants avoids
    redundant GDT calls. RLS therefore skipped (BYPASSRLS reads
    suffice).
    """

    __tablename__ = "tax_id_validations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    mst: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # `active` | `suspended` | `closed` | `not_found`
    gdt_status: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    registered_at: Mapped[date | None] = mapped_column(Date)
    business_type: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
