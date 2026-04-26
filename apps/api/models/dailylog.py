"""DailyLog — daily field reports (manpower, weather, equipment, narrative)
with LLM-assisted observation extraction and SiteEye safety hits feeding in.

Three concerns, four tables:

  1. `daily_logs` — one row per (project, log_date). Captures the day's
     weather, supervisor, and free-text narrative. The narrative is the
     input to the AI extraction pipeline that generates observations.

  2. Detail tables — `daily_log_manpower` and `daily_log_equipment` —
     normalized so we can query "average mason headcount this month" or
     "which equipment had > 50% downtime" without parsing JSON.

  3. `daily_log_observations` — granular issue/risk entries. Each one is
     either typed manually, extracted by the LLM from the narrative, or
     synthesized from a SiteEye safety incident on the same day. The
     `source` column distinguishes them so the UI can label provenance
     and operators can filter "show me only AI-generated risks I haven't
     reviewed yet".

The cross-module link to SiteEye is via `related_safety_incident_id`
(nullable). When SiteEye fires a hit on the same project on the same
day, a sync job (out of scope here — see services/dailylog_sync.py
when added) inserts an observation pointing at it. The observation
holds the snippet so the daily log surface stays self-contained even
if the underlying incident is archived.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class DailyLog(Base):
    __tablename__ = "daily_logs"

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
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Free-form weather block: { temp_c, conditions, precipitation_mm,
    # wind_kph, humidity_pct }. JSONB so we don't lock in an exact schema.
    weather: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    supervisor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    narrative: Mapped[str | None] = mapped_column(Text)
    work_completed: Mapped[str | None] = mapped_column(Text)
    issues_observed: Mapped[str | None] = mapped_column(Text)
    # draft | submitted | approved
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    extracted_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class DailyLogManpower(Base):
    __tablename__ = "daily_log_manpower"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    log_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("daily_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade: Mapped[str] = mapped_column(Text, nullable=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hours_worked: Mapped[float | None] = mapped_column(Numeric(6, 2))
    foreman: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class DailyLogEquipment(Base):
    __tablename__ = "daily_log_equipment"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    log_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("daily_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hours_used: Mapped[float | None] = mapped_column(Numeric(6, 2))
    # active | idle | broken | left_site
    state: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text)


class DailyLogObservation(Base):
    __tablename__ = "daily_log_observations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    log_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("daily_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # risk | issue | delay | milestone | safety | quality | productivity
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # low | medium | high | critical
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # manual | llm_extracted | siteeye_hit
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    related_safety_incident_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("safety_incidents.id", ondelete="SET NULL"),
    )
    # open | in_progress | resolved | dismissed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
