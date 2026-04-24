from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, Text

TZ = DateTime(timezone=True)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Ensure referenced parent tables (organizations, users, projects) are registered
# on the shared Base.metadata before SQLAlchemy resolves ForeignKey columns.
from . import core  # noqa: F401


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="todo", nullable=False)
    priority: Mapped[str] = mapped_column(Text, default="normal", nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    phase: Mapped[str | None] = mapped_column(Text)
    discipline: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    position: Mapped[Decimal | None] = mapped_column(Numeric)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ)


class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="upcoming", nullable=False)
    achieved_at: Mapped[datetime | None] = mapped_column(TZ)


class ChangeOrder(Base):
    __tablename__ = "change_orders"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="draft", nullable=False)
    initiator: Mapped[str | None] = mapped_column(Text)
    cost_impact_vnd: Mapped[int | None] = mapped_column(BigInteger)
    schedule_impact_days: Mapped[int | None] = mapped_column(Integer)
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    approved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ)


class MeetingNote(Base):
    __tablename__ = "meeting_notes"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    attendees: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    raw_notes: Mapped[str | None] = mapped_column(Text)
    ai_structured: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ)


class ClientReport(Base):
    __tablename__ = "client_reports"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict | None] = mapped_column(JSONB)
    rendered_html: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="draft", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    sent_to: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(TZ)
