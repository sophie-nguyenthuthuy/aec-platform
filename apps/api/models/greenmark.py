"""GREENMARK models — VGBC LOTUS + IFC EDGE green-building scoring.

Two rating systems share the data model:

  * **LOTUS** (VGBC) — point-based, 7 categories (Energy, Water, Materials,
    IEQ, Site, Operations, Innovation). Cert levels Certified / Silver /
    Gold / Platinum scale by total points.
  * **EDGE** (IFC) — savings-based, 3 categories (Energy, Water, Materials).
    Cert levels EDGE Certified / Advanced / Zero scale by ≥20% / ≥40% /
    net-zero savings vs baseline.

A `GreenCertification` row models the project's pursuit of a single
system + target level. `GreenCredit` rows are the per-strategy line
items (LOTUS calls them "credits", EDGE calls them "measures"; we keep
one table since the shape is identical).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class GreenCertification(Base):
    """Top-level certification pursuit.

    `achieved_score` / `max_score` are de-normalised onto the header for
    fast list-card rendering. The scoring endpoint recomputes both from
    the credit table and persists.
    """

    __tablename__ = "green_certifications"

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
    # `lotus_nr` | `lotus_homes` | `lotus_bio` | `lotus_intl` | `edge`
    system: Mapped[str] = mapped_column(Text, nullable=False)
    # LOTUS: certified | silver | gold | platinum
    # EDGE: edge_certified | edge_advanced | edge_zero
    target_level: Mapped[str] = mapped_column(Text, nullable=False)
    achieved_level: Mapped[str | None] = mapped_column(Text)
    # `planning` | `self_assessment` | `submitted` | `provisional` |
    # `final_cert` | `rejected` | `expired`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planning")
    # Aggregate scores. EDGE expresses savings as percentages — we
    # still use the points table (max = 100) and store savings_pct on
    # credit rows.
    achieved_points: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"))
    max_points: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"))
    # Project brief — gross floor area, occupancy, climate zone, etc.
    # Free-shape JSON; the scoring engine reads what's relevant for the
    # selected system.
    project_brief: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    certification_no: Mapped[str | None] = mapped_column(Text)
    awarded_at: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    assessor_name: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        # One pursuit per (project, system) — a project can pursue
        # both LOTUS and EDGE simultaneously, but not two of the same.
        UniqueConstraint("project_id", "system", name="uq_green_certifications_project_system"),
    )


class GreenCredit(Base):
    """One credit / measure within a certification.

    `code` is the standards body identifier (e.g. "LOTUS-EN-01" for
    Energy Performance, "EDGE-EN-3" for cooling system). The seed
    catalog (see routers.greenmark) populates these from a static dict
    per system; user-added credits use a custom code prefix.

    `claimed_points` is the project team's self-claim; `awarded_points`
    is what the assessor accepts after review. Until verification, the
    score uses `claimed_points`; post-verification it uses
    `awarded_points`.
    """

    __tablename__ = "green_credits"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    certification_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("green_certifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # `not_attempted` | `targeted` | `documented` | `verified` |
    # `rejected`
    status: Mapped[str] = mapped_column(Text, nullable=False, default="not_attempted")
    max_points: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"))
    claimed_points: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"))
    awarded_points: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"))
    # EDGE-specific: computed savings vs baseline (e.g. {"savings_pct":
    # 0.32, "baseline_kwh_m2y": 145, "design_kwh_m2y": 98}).
    computed_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_file_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewer_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(TZ)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("certification_id", "code", name="uq_green_credits_cert_code"),
    )
