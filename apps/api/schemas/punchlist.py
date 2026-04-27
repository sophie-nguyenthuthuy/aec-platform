"""Pydantic schemas for the Punch List module."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Enums ----------


class PunchListStatus(StrEnum):
    open = "open"
    in_review = "in_review"
    signed_off = "signed_off"
    cancelled = "cancelled"


class PunchItemStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    fixed = "fixed"
    verified = "verified"
    waived = "waived"


class PunchTrade(StrEnum):
    architectural = "architectural"
    mep = "mep"
    structural = "structural"
    civil = "civil"
    landscape = "landscape"
    other = "other"


class PunchSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


# ---------- PunchList ----------


class PunchListCreate(BaseModel):
    project_id: UUID
    name: str
    walkthrough_date: date
    owner_attendees: str | None = None
    notes: str | None = None


class PunchListUpdate(BaseModel):
    name: str | None = None
    walkthrough_date: date | None = None
    status: PunchListStatus | None = None
    owner_attendees: str | None = None
    notes: str | None = None


class PunchList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    walkthrough_date: date
    status: PunchListStatus | str
    owner_attendees: str | None = None
    notes: str | None = None
    signed_off_at: datetime | None = None
    signed_off_by: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Cheap counters merged in by the router for the list-card view.
    total_items: int = 0
    open_items: int = 0
    fixed_items: int = 0
    verified_items: int = 0


# ---------- PunchItem ----------


class PunchItemCreate(BaseModel):
    description: str
    location: str | None = None
    trade: PunchTrade = PunchTrade.architectural
    severity: PunchSeverity = PunchSeverity.medium
    photo_id: UUID | None = None
    assigned_user_id: UUID | None = None
    due_date: date | None = None
    notes: str | None = None


class PunchItemUpdate(BaseModel):
    description: str | None = None
    location: str | None = None
    trade: PunchTrade | None = None
    severity: PunchSeverity | None = None
    status: PunchItemStatus | None = None
    photo_id: UUID | None = None
    assigned_user_id: UUID | None = None
    due_date: date | None = None
    notes: str | None = None


class PunchItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    list_id: UUID
    item_number: int
    description: str
    location: str | None = None
    trade: PunchTrade | str
    severity: PunchSeverity | str
    status: PunchItemStatus | str
    photo_id: UUID | None = None
    assigned_user_id: UUID | None = None
    due_date: date | None = None
    fixed_at: datetime | None = None
    verified_at: datetime | None = None
    verified_by: UUID | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PunchListDetail(BaseModel):
    list: PunchList
    items: list[PunchItem] = Field(default_factory=list)


class SignOffRequest(BaseModel):
    notes: str | None = None
