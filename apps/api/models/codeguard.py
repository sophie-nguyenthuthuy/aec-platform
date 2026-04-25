from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CHAR, Date, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Postgres columns are `timestamp with time zone`; mirror at the ORM layer so
# asyncpg round-trips tz-aware datetimes cleanly.
TZ = DateTime(timezone=True)


class Regulation(Base):
    __tablename__ = "regulations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    code_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict | None] = mapped_column(JSONB)
    raw_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, default="vi", nullable=False)


class RegulationChunk(Base):
    __tablename__ = "regulation_chunks"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    regulation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("regulations.id", ondelete="CASCADE")
    )
    section_ref: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # `embedding` column (vector(3072)) is managed by raw SQL in the migration;
    # SQLAlchemy models never read/write it directly — the AI pipeline uses
    # raw SQL with the pgvector cast.


class ComplianceCheck(Base):
    __tablename__ = "compliance_checks"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    check_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    input: Mapped[dict | None] = mapped_column(JSONB)
    findings: Mapped[list | None] = mapped_column(JSONB)
    regulations_referenced: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True))
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TZ)


class PermitChecklist(Base):
    __tablename__ = "permit_checklists"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(TZ)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
