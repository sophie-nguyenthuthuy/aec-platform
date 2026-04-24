"""Pydantic schemas for BIDRADAR module."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Enums ----------

class TenderSource(str, Enum):
    mua_sam_cong_vn = "mua-sam-cong.gov.vn"
    philgeps_ph = "philgeps.gov.ph"
    egp_th = "egp.go.th"
    eprocurement_id = "eproc.lkpp.go.id"
    gebiz_sg = "gebiz.gov.sg"
    other = "other"


class MatchStatus(str, Enum):
    new = "new"
    saved = "saved"
    pursuing = "pursuing"
    passed = "passed"


class CompetitionLevel(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    very_high = "very_high"


# ---------- Tender ----------

class TenderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    external_id: str
    title: str
    issuer: str | None = None
    type: str | None = None
    budget_vnd: int | None = None
    currency: str = "VND"
    country_code: str = "VN"
    province: str | None = None
    disciplines: list[str] | None = None
    project_types: list[str] | None = None
    submission_deadline: datetime | None = None
    published_at: datetime | None = None
    raw_url: str | None = None


class TenderDetail(TenderSummary):
    description: str | None = None
    scraped_at: datetime | None = None


class TenderListFilters(BaseModel):
    country_code: str | None = None
    province: str | None = None
    discipline: str | None = None
    min_budget_vnd: int | None = Field(default=None, ge=0)
    max_budget_vnd: int | None = Field(default=None, ge=0)
    deadline_before: datetime | None = None
    q: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# ---------- Firm profile ----------

class FirmProfileInput(BaseModel):
    disciplines: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    provinces: list[str] = Field(default_factory=list)
    min_budget_vnd: int | None = Field(default=None, ge=0)
    max_budget_vnd: int | None = Field(default=None, ge=0)
    team_size: int | None = Field(default=None, ge=0)
    active_capacity_pct: float | None = Field(default=None, ge=0, le=100)
    past_wins: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class FirmProfile(FirmProfileInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    updated_at: datetime


# ---------- AI recommendation ----------

class AIRecommendation(BaseModel):
    match_score: float = Field(ge=0, le=100)
    estimated_value_vnd: int | None = None
    competition_level: CompetitionLevel
    win_probability: float = Field(ge=0, le=1)
    recommended_bid: bool
    reasoning: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


# ---------- Tender match ----------

class TenderMatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tender_id: UUID
    match_score: float | None = None
    estimated_value_vnd: int | None = None
    competition_level: str | None = None
    win_probability: float | None = None
    recommended_bid: bool | None = None
    ai_recommendation: AIRecommendation | dict[str, Any] | None = None
    status: MatchStatus
    proposal_id: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class TenderMatchWithTender(TenderMatch):
    tender: TenderSummary


class MatchListFilters(BaseModel):
    status: MatchStatus | None = None
    min_score: float | None = Field(default=None, ge=0, le=100)
    recommended_only: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class UpdateMatchStatusRequest(BaseModel):
    status: MatchStatus


# ---------- Scrape + score ----------

class ScrapeRequest(BaseModel):
    source: TenderSource
    max_pages: int = Field(default=5, ge=1, le=50)


class ScrapeResult(BaseModel):
    source: str
    tenders_found: int
    new_tenders: int
    matches_created: int
    started_at: datetime
    completed_at: datetime


class ScoreMatchesRequest(BaseModel):
    tender_ids: list[UUID] | None = None
    rescore_existing: bool = False


class ScoreMatchesResult(BaseModel):
    scored: int
    recommended: int


# ---------- Proposal creation ----------

class CreateProposalRequest(BaseModel):
    match_id: UUID


class CreateProposalResponse(BaseModel):
    match_id: UUID
    proposal_id: UUID
    winwork_url: str


# ---------- Weekly digest ----------

class WeeklyDigest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    week_start: date
    week_end: date
    top_match_ids: list[UUID] = Field(default_factory=list)
    sent_to: list[str] = Field(default_factory=list)
    sent_at: datetime | None = None
    created_at: datetime


class SendDigestRequest(BaseModel):
    recipients: list[EmailStr]
    top_n: int = Field(default=5, ge=1, le=20)
