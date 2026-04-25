"""SQLAlchemy models for BIDRADAR module."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CHAR, Date, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Postgres columns are `timestamp with time zone`; mirror at the ORM layer.
TZ = DateTime(timezone=True)


class Tender(Base):
    __tablename__ = "tenders"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    budget_vnd: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(Text, default="VND")
    country_code: Mapped[str] = mapped_column(CHAR(2), default="VN")
    province: Mapped[str | None] = mapped_column(Text)
    disciplines: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    project_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    submission_deadline: Mapped[datetime | None] = mapped_column(TZ)
    published_at: Mapped[datetime | None] = mapped_column(TZ)
    description: Mapped[str | None] = mapped_column(Text)
    raw_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    scraped_at: Mapped[datetime] = mapped_column(TZ)


class FirmProfile(Base):
    __tablename__ = "firm_profiles"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    disciplines: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    project_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    provinces: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    min_budget_vnd: Mapped[int | None] = mapped_column(BigInteger)
    max_budget_vnd: Mapped[int | None] = mapped_column(BigInteger)
    team_size: Mapped[int | None] = mapped_column(Integer)
    active_capacity_pct: Mapped[float | None] = mapped_column(Numeric)
    past_wins: Mapped[list] = mapped_column(JSONB, default=list)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    updated_at: Mapped[datetime] = mapped_column(TZ)


class TenderMatch(Base):
    __tablename__ = "tender_matches"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    tender_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False
    )
    match_score: Mapped[float | None] = mapped_column(Numeric)
    estimated_value_vnd: Mapped[int | None] = mapped_column(BigInteger)
    competition_level: Mapped[str | None] = mapped_column(Text)
    win_probability: Mapped[float | None] = mapped_column(Numeric)
    recommended_bid: Mapped[bool | None] = mapped_column(Boolean)
    ai_recommendation: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="new")
    proposal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ)


class TenderDigest(Base):
    __tablename__ = "tender_digests"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    top_match_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    sent_to: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ)
