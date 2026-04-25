"""Pydantic schemas for the cross-module project hub endpoints.

These schemas surface a compact, per-module status roll-up for a project so
the dashboard UI can render a single "state of the project" view without
fanning out to every module's endpoint.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Per-module roll-ups ----------


class WinworkStatus(BaseModel):
    """Link back to the proposal that seeded this project, if any."""

    proposal_id: UUID | None = None
    proposal_status: str | None = None
    total_fee_vnd: int | None = None


class CostpulseStatus(BaseModel):
    estimate_count: int = 0
    approved_count: int = 0
    latest_estimate_id: UUID | None = None
    latest_total_vnd: int | None = None


class PulseStatus(BaseModel):
    tasks_todo: int = 0
    tasks_in_progress: int = 0
    tasks_done: int = 0
    open_change_orders: int = 0
    upcoming_milestones: int = 0


class DrawbridgeStatus(BaseModel):
    document_count: int = 0
    open_rfi_count: int = 0
    unresolved_conflict_count: int = 0


class HandoverStatus(BaseModel):
    package_count: int = 0
    open_defect_count: int = 0
    warranty_active_count: int = 0
    warranty_expiring_count: int = 0


class SiteeyeStatus(BaseModel):
    visit_count: int = 0
    open_safety_incident_count: int = 0


class CodeguardStatus(BaseModel):
    compliance_check_count: int = 0
    permit_checklist_count: int = 0


# ---------- Aggregate project views ----------


class ProjectSummary(BaseModel):
    """Compact card-style projection used by the list endpoint."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    type: str | None = None
    status: str
    budget_vnd: int | None = None
    area_sqm: float | None = None
    address: dict[str, Any] = Field(default_factory=dict)
    start_date: date | None = None
    end_date: date | None = None
    created_at: datetime
    # Cheap counters; loaded via a single per-project summary query.
    open_tasks: int = 0
    open_change_orders: int = 0
    document_count: int = 0


class ProjectDetail(BaseModel):
    """Full per-module roll-up for a single project."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    type: str | None = None
    status: str
    budget_vnd: int | None = None
    area_sqm: float | None = None
    floors: int | None = None
    address: dict[str, Any] = Field(default_factory=dict)
    start_date: date | None = None
    end_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    winwork: WinworkStatus = Field(default_factory=WinworkStatus)
    costpulse: CostpulseStatus = Field(default_factory=CostpulseStatus)
    pulse: PulseStatus = Field(default_factory=PulseStatus)
    drawbridge: DrawbridgeStatus = Field(default_factory=DrawbridgeStatus)
    handover: HandoverStatus = Field(default_factory=HandoverStatus)
    siteeye: SiteeyeStatus = Field(default_factory=SiteeyeStatus)
    codeguard: CodeguardStatus = Field(default_factory=CodeguardStatus)
