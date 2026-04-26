"""Pydantic schemas for CostPulse module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class MaterialCategory(StrEnum):
    concrete = "concrete"
    steel = "steel"
    finishing = "finishing"
    mep = "mep"
    timber = "timber"
    masonry = "masonry"
    other = "other"


class EstimateStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    superseded = "superseded"


class EstimateConfidence(StrEnum):
    rough_order = "rough_order"
    preliminary = "preliminary"
    detailed = "detailed"


class EstimateMethod(StrEnum):
    ai_generated = "ai_generated"
    manual = "manual"
    imported = "imported"


class RfqStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    responding = "responding"
    closed = "closed"


class PriceSource(StrEnum):
    government = "government"
    supplier = "supplier"
    crowdsource = "crowdsource"


class BoqItemSource(StrEnum):
    ai_extracted = "ai_extracted"
    manual = "manual"
    price_db = "price_db"


# ---------- Prices ----------


class MaterialPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    material_code: str
    name: str
    category: MaterialCategory | None = None
    unit: str
    price_vnd: Decimal
    price_usd: Decimal | None = None
    province: str | None = None
    source: PriceSource | None = None
    effective_date: date
    expires_date: date | None = None
    supplier_id: UUID | None = None


class MaterialPriceQuery(BaseModel):
    q: str | None = Field(default=None, description="Full-text name/code search")
    material_code: str | None = None
    category: MaterialCategory | None = None
    province: str | None = None
    as_of: date | None = Field(default=None, description="Effective as of this date")
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class PriceHistoryPoint(BaseModel):
    effective_date: date
    price_vnd: Decimal
    province: str | None = None
    source: PriceSource | None = None


class PriceHistoryResponse(BaseModel):
    material_code: str
    name: str
    unit: str
    points: list[PriceHistoryPoint]
    pct_change_30d: float | None = None
    pct_change_1y: float | None = None


# ---------- Estimates ----------


class EstimateFromBriefRequest(BaseModel):
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    project_type: str = Field(description="e.g. residential, commercial, villa, factory")
    area_sqm: float = Field(gt=0)
    floors: int = Field(ge=1)
    province: str = Field(description="e.g. Hanoi, HCMC")
    quality_tier: Literal["economy", "standard", "premium"] = "standard"
    structure_type: Literal["reinforced_concrete", "steel", "mixed"] = "reinforced_concrete"
    notes: str | None = None


class EstimateFromDrawingsRequest(BaseModel):
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    drawing_file_ids: list[UUID] = Field(min_length=1, max_length=50)
    province: str
    include_contingency_pct: float = Field(default=10.0, ge=0, le=50)


class BoqItemIn(BaseModel):
    id: UUID | None = None
    parent_id: UUID | None = None
    sort_order: int = 0
    code: str | None = None
    description: str = Field(min_length=1)
    unit: str | None = None
    quantity: Decimal | None = None
    unit_price_vnd: Decimal | None = None
    total_price_vnd: Decimal | None = None
    material_code: str | None = None
    source: BoqItemSource | None = None
    notes: str | None = None


class BoqItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    estimate_id: UUID
    parent_id: UUID | None = None
    sort_order: int
    code: str | None = None
    description: str
    unit: str | None = None
    quantity: Decimal | None = None
    unit_price_vnd: Decimal | None = None
    total_price_vnd: Decimal | None = None
    material_code: str | None = None
    source: BoqItemSource | None = None
    notes: str | None = None


class EstimateCreate(BaseModel):
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    method: EstimateMethod = EstimateMethod.manual
    confidence: EstimateConfidence = EstimateConfidence.preliminary
    items: list[BoqItemIn] = Field(default_factory=list)


class EstimateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None = None
    name: str
    version: int
    status: EstimateStatus
    total_vnd: int | None = None
    confidence: EstimateConfidence | None = None
    method: EstimateMethod | None = None
    created_by: UUID | None = None
    approved_by: UUID | None = None
    created_at: datetime


class EstimateDetail(EstimateSummary):
    items: list[BoqItemOut] = Field(default_factory=list)


class UpdateBoqRequest(BaseModel):
    items: list[BoqItemIn]
    recompute_totals: bool = True


# ---------- Suppliers ----------


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID | None = None
    name: str
    categories: list[str] = Field(default_factory=list)
    provinces: list[str] = Field(default_factory=list)
    contact: dict[str, Any] = Field(default_factory=dict)
    verified: bool
    rating: Decimal | None = None
    created_at: datetime


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    categories: list[str] = Field(default_factory=list)
    provinces: list[str] = Field(default_factory=list)
    contact: dict[str, Any] = Field(default_factory=dict)


# ---------- RFQ ----------


class RfqCreate(BaseModel):
    project_id: UUID | None = None
    estimate_id: UUID | None = None
    supplier_ids: list[UUID] = Field(min_length=1)
    deadline: date | None = None
    message: str | None = None
    material_codes: list[str] = Field(default_factory=list)


class RfqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None = None
    estimate_id: UUID | None = None
    status: RfqStatus
    sent_to: list[UUID] = Field(default_factory=list)
    responses: list[dict[str, Any]] = Field(default_factory=list)
    deadline: date | None = None
    created_at: datetime


# ---------- Analytics ----------


class CostBenchmarkQuery(BaseModel):
    project_type: str | None = None
    province: str | None = None
    quality_tier: Literal["economy", "standard", "premium"] | None = None


class CostBenchmarkBucket(BaseModel):
    project_type: str
    province: str | None = None
    quality_tier: str | None = None
    cost_per_sqm_vnd_p25: int
    cost_per_sqm_vnd_median: int
    cost_per_sqm_vnd_p75: int
    sample_size: int


class CostBenchmarkResponse(BaseModel):
    buckets: list[CostBenchmarkBucket]


# ---------- AI pipeline output ----------


class AiEstimateResult(BaseModel):
    estimate_id: UUID
    total_vnd: int
    confidence: EstimateConfidence
    items: list[BoqItemOut]
    warnings: list[str] = Field(default_factory=list)
    missing_price_codes: list[str] = Field(default_factory=list)
