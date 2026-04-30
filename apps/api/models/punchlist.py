"""Punch list — owner walkthrough items (separate workflow from Handover defects).

Why a new module instead of overloading Handover.Defect?

  * `defects` are designer-flagged during construction (column out of plumb,
    spec mismatch). Handover's defect lifecycle goes through QC review
    before a hand-off package can close.
  * `punch_items` are owner-walkthrough findings during commissioning
    ("paint scuff in lobby", "outlet B-103 dead"). Different cadence
    (one walkthrough = one punch list, with the owner attending),
    different sign-off (the owner physically initials each line on the
    list at acceptance), and a different scope of trades involved.

Two tables:

  * `punch_lists` — one per (project, walkthrough_date). The list as a
    whole has a status (open / in_review / signed_off) and an owner
    signature stamp (`signed_off_at`, `signed_off_by`).
  * `punch_items` — granular findings. Each row carries a location
    (room/floor), trade (architectural / mep / structural / civil /
    landscape), photo file_id (optional), assigned_subcontractor_id,
    a status (open / in_progress / fixed / verified / waived), and
    timestamps for the workflow transitions.

Cross-module hooks:
  * `project_id` FK as usual.
  * `photo_id` FK to files.id (for image attachments).
  * `assigned_user_id` FK to users.id (the supe / sub PM).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class PunchList(Base):
    __tablename__ = "punch_lists"

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
    name: Mapped[str] = mapped_column(Text, nullable=False)
    walkthrough_date: Mapped[date] = mapped_column(Date, nullable=False)
    # open | in_review | signed_off | cancelled
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    owner_attendees: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    signed_off_at: Mapped[datetime | None] = mapped_column(TZ)
    signed_off_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class PunchItem(Base):
    __tablename__ = "punch_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    list_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("punch_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 1-based, unique per list (owner-friendly numbering).
    item_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Free text "Lobby / Floor 3" — owners describe locations naturally.
    location: Mapped[str | None] = mapped_column(Text)
    # architectural | mep | structural | civil | landscape | other
    trade: Mapped[str] = mapped_column(Text, nullable=False, default="architectural")
    # low | medium | high
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    # open | in_progress | fixed | verified | waived
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    photo_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"))
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    fixed_at: Mapped[datetime | None] = mapped_column(TZ)
    verified_at: Mapped[datetime | None] = mapped_column(TZ)
    verified_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
