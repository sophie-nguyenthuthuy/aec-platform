"""BONDLINE models — VN construction bonds (bảo lãnh ngân hàng).

Three statutory bond types are common in VN public + large private
contracts (per Luật Đấu thầu 2023 + NĐ 24/2024/NĐ-CP):

  * **bid**         — bảo lãnh dự thầu (1-3% of bid value)
  * **performance** — bảo lãnh thực hiện hợp đồng (5-10%)
  * **advance**     — bảo lãnh tạm ứng (back-to-back with advance %)

Bonds are issued by VN banks (Vietcombank, BIDV, Vietinbank, TPB, …)
and have a statutory expiry. Released back to the contractor when the
underlying obligation is discharged; called by the owner if the
contractor defaults.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class Bond(Base):
    """One bank-issued bond on a project."""

    __tablename__ = "bonds"

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
    # `bid` | `performance` | `advance` | `warranty` (less common —
    # 5-year bảo hành công trình bond)
    bond_type: Mapped[str] = mapped_column(Text, nullable=False)
    bond_no: Mapped[str] = mapped_column(Text, nullable=False)
    # Bank code from VN banking ecosystem. We don't FK to a banks table
    # — the set is small and stable enough to keep as free text plus a
    # CHECK constraint at the migration level.
    issuing_bank: Mapped[str] = mapped_column(Text, nullable=False)
    bank_branch: Mapped[str | None] = mapped_column(Text)
    beneficiary_name: Mapped[str] = mapped_column(Text, nullable=False)
    beneficiary_mst: Mapped[str | None] = mapped_column(Text)
    # Money columns in VND. Standard contract terms cap performance
    # bonds at 10% of contract value, so BIGINT is plenty.
    face_amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Contract value the bond is computed against — kept for the
    # face_amount / contract_value ratio audit (e.g. catches a bond
    # that's 0.5% of the contract when 5% was contracted).
    contract_value_vnd: Mapped[int | None] = mapped_column(BigInteger)
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="VND")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # `active` | `released` | `claimed` | `expired` | `cancelled`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    released_at: Mapped[date | None] = mapped_column(Date)
    released_reason: Mapped[str | None] = mapped_column(Text)
    # Reference to the original signed bond letter (scanned PDF).
    bond_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    contract_no: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        # An (org, bank, bond_no) triple is unique — banks issue unique
        # numbers, so two rows with the same (bank, bond_no) is a data
        # quality bug.
        UniqueConstraint("organization_id", "issuing_bank", "bond_no", name="uq_bonds_org_bank_no"),
    )


class BondClaim(Base):
    """A claim filed against an active bond.

    Two distinct paths:
      * Owner-initiated default claim — owner calls the bond when the
        contractor defaults.
      * Amendment — extension request to the bank (date push, amount
        increase). Kept here for the audit trail.
    """

    __tablename__ = "bond_claims"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    bond_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bonds.id", ondelete="CASCADE"),
        nullable=False,
    )
    # `default_call` | `extension` | `amount_increase` | `cancellation`
    claim_type: Mapped[str] = mapped_column(Text, nullable=False)
    claim_amount_vnd: Mapped[int | None] = mapped_column(BigInteger)
    # `pending` | `accepted` | `partial` | `rejected` | `withdrawn`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)
    decided_date: Mapped[date | None] = mapped_column(Date)
    decided_amount_vnd: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
    evidence_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
