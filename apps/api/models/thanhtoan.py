"""THANHTOAN models — monthly progress payment claims (hồ sơ thanh toán giai đoạn).

VN tax math anchored in the data model:

  subtotal       = Σ(this_period_qty × unit_rate_vnd)
  vat_vnd        = subtotal × vat_pct
  gross          = subtotal + vat_vnd
  retention_vnd  = gross × retention_pct           (giữ lại bảo hành — 5%)
  tndn_vnd       = subtotal × tndn_pct             (TNDN tạm thu — 1%)
  net_payable    = gross - retention_vnd - tndn_vnd

`cumulative_prev_vnd` carries the sum of prior **approved** claims on
the same project so completion-percentage math doesn't drift when an
earlier claim is later voided.

All monetary columns are BIGINT VND (no fractions). Percentages are
NUMERIC(5,4) so 8.00% serialises as `0.0800`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class PaymentClaim(Base):
    """Header for a payment claim covering one period.

    `claim_no` is unique per (organization, project) — the application
    layer assigns sequential numbers (PT-2026-01, PT-2026-02, …) and
    the UNIQUE constraint blocks accidental duplicates.

    Signoff tracking is kept inline (cdt / tvgs columns) rather than as
    a separate signatories table because — unlike NghieThu — the legal
    parties on a payment claim are fixed (CĐT + TVGS); the contractor
    is implicit as the issuer.
    """

    __tablename__ = "payment_claims"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_no: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # `draft` | `submitted` | `in_review` | `approved` | `rejected` |
    # `paid` | `cancelled`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")

    # ---------- Money columns (VND, no fractions) ----------
    subtotal_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    vat_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0800"))
    vat_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    gross_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retention_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0500"))
    retention_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tndn_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0100"))
    tndn_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_payable_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Sum of prior **approved** claims on this project — frozen at
    # submit time, so a downstream void doesn't rewrite history.
    cumulative_prev_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # ---------- Workflow timestamps ----------
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    cdt_signed_at: Mapped[datetime | None] = mapped_column(TZ)
    cdt_signed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    cdt_decision: Mapped[str | None] = mapped_column(Text)  # approve | reject
    cdt_comment: Mapped[str | None] = mapped_column(Text)
    tvgs_signed_at: Mapped[datetime | None] = mapped_column(TZ)
    tvgs_signed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    tvgs_decision: Mapped[str | None] = mapped_column(Text)
    tvgs_comment: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    rejected_at: Mapped[datetime | None] = mapped_column(TZ)
    due_at: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[date | None] = mapped_column(Date)
    payment_reference: Mapped[str | None] = mapped_column(Text)
    pdf_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (UniqueConstraint("project_id", "claim_no", name="uq_payment_claims_project_claim_no"),)


class PaymentClaimLine(Base):
    """Per work-item line on a claim.

    `cumulative_qty` is the running total **including** the current
    period — kept inline so the PDF doesn't need a window query at
    render time. The router maintains it on insert / update.
    """

    __tablename__ = "payment_claim_lines"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payment_claims.id", ondelete="CASCADE"),
        nullable=False,
    )
    # BoQ work-item code — free text so we don't FK across module
    # boundaries (costpulse owns the BoQ tables).
    work_item_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    planned_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    this_period_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    cumulative_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    unit_rate_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    this_period_amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cumulative_amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Stored on the row so the UI can render % without a costly client
    # re-divide; null planned_qty → percent is null.
    completion_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    notes: Mapped[str | None] = mapped_column(Text)
    evidence_file_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (UniqueConstraint("claim_id", "work_item_code", name="uq_payment_claim_lines_claim_workitem"),)


class PaymentClaimEvidence(Base):
    """Optional cover-level evidence (vs per-line `evidence_file_ids`).

    Reuses the same kind enum as NghieThu for consistency — site teams
    don't need to learn two vocabularies.
    """

    __tablename__ = "payment_claim_evidence"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payment_claims.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    external_ref: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
