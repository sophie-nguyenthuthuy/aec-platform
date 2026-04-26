"""Pydantic schemas for the ChangeOrder module.

The base ChangeOrder model lives in pulse.py. This module covers the
extension tables (sources, line items, approvals, AI candidates) plus
the AI extract / analyze request shapes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class CoStatus(StrEnum):
    draft = "draft"
    submitted = "submitted"
    reviewed = "reviewed"
    approved = "approved"
    rejected = "rejected"
    executed = "executed"
    cancelled = "cancelled"


class CoSourceKind(StrEnum):
    rfi = "rfi"
    observation = "observation"
    email = "email"
    manual = "manual"
    external = "external"


class LineKind(StrEnum):
    add = "add"
    delete = "delete"
    substitute = "substitute"


class CandidateSourceKind(StrEnum):
    rfi = "rfi"
    email = "email"
    manual_paste = "manual_paste"


# ---------- ChangeOrder (base table — already exists in pulse) ----------


class ChangeOrderCreate(BaseModel):
    project_id: UUID
    title: str
    description: str | None = None
    number: str | None = None  # auto-assigned if omitted
    initiator: str | None = None
    cost_impact_vnd: int | None = None
    schedule_impact_days: int | None = None


class ChangeOrderUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: CoStatus | None = None
    initiator: str | None = None
    cost_impact_vnd: int | None = None
    schedule_impact_days: int | None = None


class ChangeOrder(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    number: str
    title: str
    description: str | None = None
    status: CoStatus | str
    initiator: str | None = None
    cost_impact_vnd: int | None = None
    schedule_impact_days: int | None = None
    ai_analysis: dict[str, Any] | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    created_at: datetime


# ---------- Sources ----------


class SourceCreate(BaseModel):
    source_kind: CoSourceKind
    rfi_id: UUID | None = None
    observation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class Source(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    change_order_id: UUID
    source_kind: CoSourceKind | str
    rfi_id: UUID | None = None
    observation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    created_at: datetime


# ---------- Line items ----------


class LineItemCreate(BaseModel):
    description: str
    line_kind: LineKind = LineKind.add
    spec_section: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_cost_vnd: int | None = None
    cost_vnd: int | None = None
    schedule_impact_days: int | None = None
    schedule_activity_id: UUID | None = None
    sort_order: int = 0
    notes: str | None = None


class LineItemUpdate(BaseModel):
    description: str | None = None
    line_kind: LineKind | None = None
    spec_section: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_cost_vnd: int | None = None
    cost_vnd: int | None = None
    schedule_impact_days: int | None = None
    schedule_activity_id: UUID | None = None
    sort_order: int | None = None
    notes: str | None = None


class LineItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    change_order_id: UUID
    description: str
    line_kind: LineKind | str
    spec_section: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_cost_vnd: int | None = None
    cost_vnd: int | None = None
    schedule_impact_days: int | None = None
    schedule_activity_id: UUID | None = None
    sort_order: int = 0
    notes: str | None = None
    created_at: datetime


# ---------- Approvals ----------


class ApprovalCreate(BaseModel):
    """Record a state transition. The router infers `from_status` from the
    CO's current `status` and updates it atomically."""

    to_status: CoStatus
    notes: str | None = None


class Approval(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    change_order_id: UUID
    from_status: CoStatus | str | None = None
    to_status: CoStatus | str
    actor_id: UUID | None = None
    notes: str | None = None
    created_at: datetime


# ---------- AI extraction / analysis ----------


class ExtractCandidatesRequest(BaseModel):
    """Either point at an RFI by id, or paste raw text (email body, etc.)."""

    project_id: UUID
    rfi_id: UUID | None = None
    text: str | None = None
    source_kind: CandidateSourceKind = CandidateSourceKind.manual_paste


class CandidateProposal(BaseModel):
    """The LLM's structured output stored on each candidate."""

    title: str
    description: str
    line_items: list[LineItemCreate] = Field(default_factory=list)
    cost_impact_vnd_estimate: int | None = None
    schedule_impact_days_estimate: int | None = None
    confidence_pct: int | None = None
    rationale: str | None = None


class Candidate(BaseModel):
    # `model_version` collides with Pydantic's protected namespace.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: UUID
    organization_id: UUID
    project_id: UUID
    source_kind: CandidateSourceKind | str
    source_rfi_id: UUID | None = None
    source_text_snippet: str | None = None
    proposal: dict[str, Any] = Field(default_factory=dict)
    model_version: str
    accepted_co_id: UUID | None = None
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    rejected_reason: str | None = None
    actor_id: UUID | None = None
    created_at: datetime


class AcceptCandidateRequest(BaseModel):
    """Optional human edits on top of the candidate before promotion."""

    title_override: str | None = None
    description_override: str | None = None


class RejectCandidateRequest(BaseModel):
    reason: str | None = None


class AnalyzeImpactRequest(BaseModel):
    """Re-run the AI cost/schedule impact analyzer on an existing CO."""

    force: bool = False


# ---------- Aggregates ----------


class ChangeOrderDetail(BaseModel):
    change_order: ChangeOrder
    sources: list[Source] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
