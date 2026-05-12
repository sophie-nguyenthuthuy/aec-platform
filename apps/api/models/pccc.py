"""PCCC models — fire safety certification per QCVN 06:2022/BXD + NĐ 136/2020.

Two distinct certifications govern a building's PCCC lifecycle:

  * **Thẩm duyệt thiết kế PCCC** — design appraisal, before construction.
    Reviews fire-resistance ratings, egress, compartmentation against
    QCVN 06:2022. Issued by PC07 (provincial fire police).
  * **Nghiệm thu PCCC** — acceptance inspection, before occupancy.
    Physical inspection by PC07 — sprinkler test, hydrant pressure,
    smoke control, etc. Result: pass / conditional / fail.

A `FireCert` row models one of these certifications. Inspections and
design-checklist items hang off it. The acceptance cert has a 5-year
validity (renewable via `recert`).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class FireCert(Base):
    """One PCCC certification for a project.

    `hazard_category` is the fire hazard class A-F per QCVN 06:2022 —
    drives the entire downstream rule set (egress widths, sprinkler
    coverage, fire-resistance ratings). `building_class` is the fire
    resistance class CO1-CO4 (CO1 = best, non-combustible).
    """

    __tablename__ = "fire_certs"

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
    # `design` (thẩm duyệt) | `acceptance` (nghiệm thu) | `recert`
    cert_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Reference / file number issued by the contractor's QA team.
    reference_no: Mapped[str] = mapped_column(Text, nullable=False)
    # `A` | `B` | `C` | `D` | `E` | `F` per QCVN 06:2022 § 3
    hazard_category: Mapped[str] = mapped_column(Text, nullable=False)
    # `CO1` | `CO2` | `CO3` | `CO4` — fire resistance class
    building_class: Mapped[str] = mapped_column(Text, nullable=False)
    height_m: Mapped[float | None] = mapped_column(Numeric(8, 2))
    floors_above: Mapped[int | None] = mapped_column(Integer)
    floors_below: Mapped[int | None] = mapped_column(Integer)
    area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    occupant_load: Mapped[int | None] = mapped_column(Integer)
    # PC07 jurisdiction (province / centrally-administered city). Stored
    # as text so cross-province transfers don't need a code table update.
    pc07_unit: Mapped[str] = mapped_column(Text, nullable=False)
    # `planning` | `submitted` | `inspection_scheduled` | `rfi` |
    # `approved` | `conditional` | `rejected` | `expired`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planning")
    submitted_date: Mapped[date | None] = mapped_column(Date)
    inspection_date: Mapped[date | None] = mapped_column(Date)
    decision_date: Mapped[date | None] = mapped_column(Date)
    decision_number: Mapped[str | None] = mapped_column(Text)
    decision_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    # PCCC acceptance cert: 5-year statutory validity (NĐ 136/2020).
    # NULL on design appraisals (those don't expire — they're a one-off
    # design-time approval).
    expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    legal_basis: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "project_id", "cert_type", "reference_no", name="uq_fire_certs_project_type_ref"
        ),
    )


class FireInspection(Base):
    """A scheduled / performed on-site inspection round.

    `findings` is a free-shape JSON list: each entry is roughly
    `{item, status, severity, location, evidence_file_ids}`. Strict
    typing lives in the Pydantic schema; the DB just stores blobs so
    inspectors can add new check categories without a migration.
    """

    __tablename__ = "fire_inspections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    cert_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("fire_certs.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    inspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    inspector_name: Mapped[str] = mapped_column(Text, nullable=False)
    inspector_org: Mapped[str | None] = mapped_column(Text)
    # `pass` | `conditional_pass` | `fail` | `rescheduled`
    overall_result: Mapped[str] = mapped_column(Text, nullable=False, default="rescheduled")
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text)
    report_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("cert_id", "round_number", name="uq_fire_inspections_cert_round"),
    )


class FireChecklistItem(Base):
    """One line of the QCVN 06:2022 design checklist.

    Items are seeded from a fixed template per `hazard_category` +
    `building_class`. Reviewers (in-house fire engineer or external
    PCCC consultant) mark each as compliant / non / N/A. The output
    is the "pre-PC07" gate that catches design issues before formal
    submission.
    """

    __tablename__ = "fire_checklist_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    cert_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("fire_certs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # E.g. "QCVN 06:2022 §5.4.3" — keeps it text so we can reference any
    # clause format without an enumeration.
    clause_ref: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # `pending` | `compliant` | `non_compliant` | `not_applicable`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewer_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    evidence_file_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    drawing_refs: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
