"""Pydantic schemas for the cross-project activity feed."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ActivityModule(StrEnum):
    pulse = "pulse"
    siteeye = "siteeye"
    handover = "handover"
    winwork = "winwork"
    drawbridge = "drawbridge"
    costpulse = "costpulse"
    codeguard = "codeguard"


class ActivityEventType(StrEnum):
    change_order_created = "change_order_created"
    task_completed = "task_completed"
    safety_incident_detected = "safety_incident_detected"
    defect_reported = "defect_reported"
    proposal_outcome_marked = "proposal_outcome_marked"
    rfi_raised = "rfi_raised"
    handover_package_delivered = "handover_package_delivered"


class ActivityEvent(BaseModel):
    """A single normalized event drawn from one module's table.

    The frontend renders these as a chronological feed; `metadata` carries
    module-specific fields (priority, severity, status, etc.) without
    needing per-module subtypes."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    project_name: str | None = None
    module: ActivityModule
    event_type: ActivityEventType
    title: str
    description: str | None = None
    timestamp: datetime
    actor_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivityFilters(BaseModel):
    project_id: UUID | None = None
    module: ActivityModule | None = None
    since_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
