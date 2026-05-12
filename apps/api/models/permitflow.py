"""PERMITFLOW models — VN construction permit chain.

Models the five-stage permit workflow that every VN construction project
walks through:

  1. chủ trương đầu tư         (investment policy decision)
  2. quy hoạch 1/500           (detailed master-plan approval)
  3. thẩm định TKCS            (basic design appraisal)
  4. giấy phép xây dựng (GPXD) (building permit)
  5. nghiệm thu PCCC           (fire-safety acceptance — sign-off to occupy)

Each project gets one `PermitDossier` and five `PermitStage` rows (one per
stage). Each round-trip with the ministry — initial submission, RFI
response, re-submission — is a `PermitSubmission` linked to a stage. The
trio (dossier, stage, submission) gives the timeline.

DDL + RLS policies live in alembic/versions/0042_permitflow.py.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class PermitDossier(Base):
    """One permit chain instance per project.

    `classification` is the cấp công trình (project grade) per QCVN
    03:2022/BXD — drives which authority appraises the TKCS (grade I /
    special → BXD central; grade II–III → SXD provincial). Stored on the
    dossier rather than computed each time because reclassification
    requires a fresh round of submissions.
    """

    __tablename__ = "permit_dossiers"

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
    # Human-friendly identifier, e.g. "Hồ sơ chính — Toà A". A project may
    # have multiple dossiers if it's a phased / multi-block development
    # where each block has its own GPXD.
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # `cap_iv` | `cap_iii` | `cap_ii` | `cap_i` | `dac_biet` — see schemas.
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    # `domestic` | `fdi` — drives whether chủ trương đầu tư goes through
    # BKHDT (FDI ≥ certain threshold) or stays at UBND tỉnh (domestic).
    investment_type: Mapped[str] = mapped_column(Text, nullable=False, default="domestic")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planning")
    # Free-form address / commune / district fields so the dossier can
    # carry data needed for GPXD application even if the parent
    # Project.address JSON is incomplete.
    location: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Land use right certificate (Sổ đỏ / GCN QSDĐ) reference. Required
    # paperwork for QH 1/500 + GPXD; we store the file id + parcel number.
    land_cert_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    land_parcel_no: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class PermitStage(Base):
    """One stage within a dossier's permit chain.

    The five stages are seeded automatically when the dossier is created
    (see `routers.permitflow.create_dossier`). Stage progression is
    sequential — a stage can't move to `submitted` until the prior stage
    is `approved`. The router enforces this gate.

    `expiry_date` is the legal validity of the approval. GPXD lapses 12
    months after issuance if construction hasn't started (Luật Xây dựng
    Art. 99). The alerts cron warns 60 / 30 / 7 days before expiry.
    """

    __tablename__ = "permit_stages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    dossier_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("permit_dossiers.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stable enum string: chu_truong_dau_tu | quy_hoach_1_500 |
    # tham_dinh_tkcs | gpxd | nghiem_thu_pccc.
    stage_code: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Authority handling this stage: BKHDT | BXD | UBND_TINH | UBND_HUYEN
    # | SXD | PC07. Auto-derived from (stage_code, classification,
    # investment_type) at seed time but mutable — e.g. a project may get
    # delegated from SXD to UBND huyện.
    authority: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="not_started")
    # Legal basis (NĐ / Luật) anchoring this stage — surfaced as a badge
    # in the UI so site managers can defend the workflow to auditors.
    legal_basis: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # Initial-submission target date. Used by the alerts cron to flag
    # stages slipping out of plan.
    target_submit_date: Mapped[date | None] = mapped_column(Date)
    submitted_date: Mapped[date | None] = mapped_column(Date)
    decision_date: Mapped[date | None] = mapped_column(Date)
    # Số quyết định / mã hồ sơ from the issuing authority.
    decision_number: Mapped[str | None] = mapped_column(Text)
    decision_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL")
    )
    # Statutory expiry of the approval, where applicable. NULL means
    # "no expiry" (most stages) — GPXD and PCCC certs are the common
    # case where this is populated.
    expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("dossier_id", "stage_code", name="uq_permit_stages_dossier_stage"),
    )


class PermitSubmission(Base):
    """One round-trip with the issuing authority.

    A stage typically has 2–5 submissions: initial submission, one or
    more RFI responses, and a final approval round. Storing each as a
    row gives the UI a clean timeline + lets us compute RFI-rate
    statistics per authority.
    """

    __tablename__ = "permit_submissions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("permit_stages.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # `initial` | `rfi_response` | `resubmission` | `withdrawal_request`
    submission_type: Mapped[str] = mapped_column(Text, nullable=False, default="initial")
    submitted_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    submitted_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Receipt number issued by the one-stop shop (số biên nhận).
    receipt_number: Mapped[str | None] = mapped_column(Text)
    # File ids that comprise this submission packet (signed PDFs + DWG).
    package_file_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    # Free-text outcome (RFI text, approval note, rejection reason).
    outcome: Mapped[str | None] = mapped_column(Text)
    # `pending` | `accepted` | `rfi_issued` | `rejected`
    outcome_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    outcome_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("stage_id", "round_number", name="uq_permit_submissions_stage_round"),
    )
