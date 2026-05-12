"""NGHIEMTHU models — statutory acceptance per Nghị định 06/2021/NĐ-CP.

Three legally distinct acceptance levels:
  * nghiệm thu công việc  (work-task acceptance)        — daily / per work item
  * nghiệm thu giai đoạn  (stage/phase acceptance)       — phase boundary
  * nghiệm thu hoàn thành (completion acceptance)        — final, enables occupancy

Each level requires a signed biên bản nghiệm thu (BBNT) with the parties
prescribed in NĐ 06/2021 Art. 11–13:
  CĐT (chủ đầu tư), TVGS (tư vấn giám sát), NT (nhà thầu) — mandatory.
  TVTK (tư vấn thiết kế), TVQLDA — optional, depending on contract.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class AcceptanceRecord(Base):
    """Top-level biên bản nghiệm thu.

    `reference_no` is the human-issued document number (e.g.
    "BBNT-2026-04-001"). Unique per (organization, year) — enforced in
    application code rather than DB constraint because the year prefix
    is parsed from the string.

    `superseded_by_id` lets a revision chain replace prior records when
    the underlying work changes. Audit-friendly: the original is kept
    intact, just marked `superseded`.
    """

    __tablename__ = "acceptance_records"

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
    # Sequential reference number — issued by the contractor's QA team
    # at time of opening the BBNT. Free-form so site teams can mirror
    # their existing numbering convention.
    reference_no: Mapped[str] = mapped_column(Text, nullable=False)
    # `cong_viec` | `giai_doan` | `hoan_thanh`
    acceptance_level: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form title (e.g. "Nghiệm thu cốt thép cột tầng 5 trục A-D").
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # `draft` | `in_signoff` | `accepted` | `rejected` | `superseded`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    # Date the actual acceptance walkthrough happened on site. May
    # differ from when signatures landed.
    acceptance_date: Mapped[date] = mapped_column(Date, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    # BoQ work-item codes this BBNT covers — joinable back to costpulse
    # (the array stays as text because BoQ codes are firm-defined and
    # not always UUIDs).
    work_item_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # JSON-encoded quantity table: list of {code, name, unit, planned,
    # actual, variance_pct}. Surfaces in the BBNT PDF as a table.
    quantities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Legal basis: drawing references, materials test reports, change
    # orders, etc. Free-shape JSON; the PDF template renders whatever
    # is here as a bulleted list.
    basis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Per NĐ 06/2021 Art. 9: a BBNT must reach a conclusion of either
    # "đạt yêu cầu" (meets requirements — proceed) or specify defects
    # to be fixed. Persisted as text so site managers can use VN.
    conclusion: Mapped[str | None] = mapped_column(Text)
    # Link to the rendered PDF blob (storage in `files`).
    pdf_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    # When this BBNT was replaced by a later revision — see class docstring.
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("acceptance_records.id", ondelete="SET NULL"),
    )
    finalized_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class AcceptanceSignatory(Base):
    """One party to an acceptance record.

    `role` encodes the statutory party (CĐT / TVGS / NT / TVTK / TVQLDA).
    `required` is set when the BBNT is opened — only required parties
    must have an `approve` decision for the record to finalize.
    """

    __tablename__ = "acceptance_signatories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("acceptance_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # The legal entity signing in this capacity. NULL when the party is
    # represented internally (e.g. our own org acting as TVGS).
    org_name: Mapped[str] = mapped_column(Text, nullable=False)
    representative_name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[str | None] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # `pending` | `approve` | `reject` | `comment_only`
    decision: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    comment: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(TZ)
    # File reference for the scanned/electronic signature, where the
    # acceptance was signed offline before being attached.
    signature_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    # User in our system who recorded the signature (audit trail —
    # NULL when imported from an external e-signature service).
    signed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        # A given (record, role, org_name) is unique — prevents two
        # rows for the same TVGS firm on the same BBNT.
        UniqueConstraint("record_id", "role", "org_name", name="uq_acceptance_signatories_record_party"),
    )


class AcceptanceEvidence(Base):
    """Attachment to an acceptance record.

    Free polymorphic shape: a row points to either a file (PDF, photo,
    drawing) or an external reference (e.g. a dailylog row ID rendered
    as a link). The PDF renderer walks these in `sort_order`.
    """

    __tablename__ = "acceptance_evidence"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("acceptance_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    # `photo` | `document` | `test_cert` | `drawing_ref` |
    # `dailylog_ref` | `task_ref`
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    # For non-file references (e.g. "/dailylog/<id>") — captures the
    # cross-module link without enforcing a hard FK across module
    # boundaries.
    external_ref: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime | None] = mapped_column(TZ)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
