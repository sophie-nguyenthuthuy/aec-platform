from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CHAR, Date, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Postgres columns are `timestamp with time zone`; mirror that at the ORM layer
# so asyncpg round-trips tz-aware datetimes without "can't subtract offset-naive
# and offset-aware" errors at flush time. See apps/api/models/pulse.py for the
# same pattern.
TZ = DateTime(timezone=True)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="draft")
    client_name: Mapped[str | None] = mapped_column(Text)
    client_email: Mapped[str | None] = mapped_column(Text)
    scope_of_work: Mapped[dict | None] = mapped_column(JSONB)
    fee_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    total_fee_vnd: Mapped[int | None] = mapped_column(BigInteger)
    total_fee_currency: Mapped[str] = mapped_column(Text, default="VND")
    valid_until: Mapped[date | None] = mapped_column(Date)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    notes: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    responded_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ)


class ProposalTemplate(Base):
    __tablename__ = "proposal_templates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    discipline: Mapped[str | None] = mapped_column(Text)
    project_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    content: Mapped[dict | None] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class FeeBenchmark(Base):
    __tablename__ = "fee_benchmarks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    discipline: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    province: Mapped[str | None] = mapped_column(Text)
    area_sqm_min: Mapped[Decimal | None] = mapped_column(Numeric)
    area_sqm_max: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_percent_low: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_percent_mid: Mapped[Decimal | None] = mapped_column(Numeric)
    fee_percent_high: Mapped[Decimal | None] = mapped_column(Numeric)
    source: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
