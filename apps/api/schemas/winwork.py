from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Discipline = Literal["architecture", "structural", "mep", "civil"]
ProposalStatus = Literal["draft", "sent", "won", "lost", "expired"]


# ---------- Nested JSON shapes ----------

class ScopeItem(BaseModel):
    id: str
    phase: str
    title: str
    description: str | None = None
    deliverables: list[str] = Field(default_factory=list)
    hours_estimate: float | None = None
    fee_vnd: int | None = None


class ScopeOfWork(BaseModel):
    items: list[ScopeItem] = Field(default_factory=list)


class FeeLine(BaseModel):
    phase: str
    label: str
    amount_vnd: int
    percent: float | None = None
    notes: str | None = None


class FeeBreakdown(BaseModel):
    lines: list[FeeLine] = Field(default_factory=list)
    subtotal_vnd: int = 0
    vat_vnd: int = 0
    total_vnd: int = 0


# ---------- Proposal ----------

class ProposalBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str = Field(min_length=1, max_length=500)
    project_id: UUID | None = None
    client_name: str | None = None
    client_email: EmailStr | None = None
    scope_of_work: ScopeOfWork | None = None
    fee_breakdown: FeeBreakdown | None = None
    total_fee_vnd: int | None = None
    total_fee_currency: str = "VND"
    valid_until: date | None = None
    notes: str | None = None


class ProposalCreate(ProposalBase):
    status: ProposalStatus = "draft"


class ProposalUpdate(BaseModel):
    title: str | None = None
    client_name: str | None = None
    client_email: EmailStr | None = None
    scope_of_work: ScopeOfWork | None = None
    fee_breakdown: FeeBreakdown | None = None
    total_fee_vnd: int | None = None
    valid_until: date | None = None
    notes: str | None = None
    status: ProposalStatus | None = None


class Proposal(ProposalBase):
    id: UUID
    status: ProposalStatus
    ai_generated: bool
    ai_confidence: Decimal | None = None
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime


class ProposalListFilters(BaseModel):
    status: ProposalStatus | None = None
    project_id: UUID | None = None
    q: str | None = None
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


# ---------- AI generation ----------

class ProposalGenerateRequest(BaseModel):
    project_type: str = Field(min_length=1)
    area_sqm: float = Field(gt=0)
    floors: int = Field(ge=1)
    location: str = Field(min_length=1)
    scope_items: list[str] = Field(min_length=1)
    client_brief: str = Field(min_length=10)
    discipline: Discipline
    language: Literal["vi", "en"] = "vi"
    project_id: UUID | None = None


class ProposalGenerateResponse(BaseModel):
    proposal: Proposal
    ai_job_id: UUID


# ---------- Fee estimation ----------

class FeeEstimateRequest(BaseModel):
    discipline: Discipline
    project_type: str
    area_sqm: float = Field(gt=0)
    country_code: str = "VN"
    province: str | None = None


class FeeEstimateResponse(BaseModel):
    fee_low_vnd: int
    fee_mid_vnd: int
    fee_high_vnd: int
    fee_percent_low: float
    fee_percent_mid: float
    fee_percent_high: float
    basis: str
    confidence: float = Field(ge=0.0, le=1.0)


# ---------- Outcome + send ----------

class ProposalOutcomeUpdate(BaseModel):
    status: Literal["won", "lost"]
    reason: str | None = None
    actual_fee_vnd: int | None = None


class SendProposalRequest(BaseModel):
    subject: str | None = None
    message: str | None = None
    cc: list[EmailStr] = Field(default_factory=list)


# ---------- Analytics ----------

class ProjectTypeWinRate(BaseModel):
    project_type: str
    total: int
    won: int
    win_rate: float


class MonthlyWinRate(BaseModel):
    month: str
    total: int
    won: int
    lost: int


class WinRateAnalytics(BaseModel):
    total: int
    won: int
    lost: int
    pending: int
    win_rate: float
    avg_fee_vnd: int
    by_project_type: list[ProjectTypeWinRate]
    by_month: list[MonthlyWinRate]


# ---------- Benchmarks ----------

class FeeBenchmark(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    discipline: Discipline
    project_type: str
    country_code: str
    province: str | None = None
    area_sqm_min: Decimal | None = None
    area_sqm_max: Decimal | None = None
    fee_percent_low: Decimal | None = None
    fee_percent_mid: Decimal | None = None
    fee_percent_high: Decimal | None = None
    source: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class BenchmarkFilters(BaseModel):
    discipline: Discipline | None = None
    project_type: str | None = None
    country_code: str = "VN"
    province: str | None = None


# ---------- Templates ----------

class ProposalTemplate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    discipline: Discipline | None = None
    project_types: list[str] = Field(default_factory=list)
    content: dict | None = None
    is_default: bool = False


class ProposalTemplateCreate(BaseModel):
    name: str
    discipline: Discipline | None = None
    project_types: list[str] = Field(default_factory=list)
    content: dict
    is_default: bool = False
