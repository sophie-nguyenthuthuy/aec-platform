"""Pydantic schemas for the cross-module 'today' inbox.

Surfaces "what needs my attention?" across the 14 modules in one shape,
avoiding 14 separate clicks. Two flavours of items:

  * `assigned_to_me` — explicit assignment via a user FK column
    (rfis.assigned_to, punch_items.assigned_user_id, defects.assignee_id).
  * `awaiting_review` — org-level pending items where assignment is
    implicit in the role (submittals ball_in_court=designer, COs awaiting
    review, AI candidates pending accept/reject).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InboxItemKind(StrEnum):
    rfi = "rfi"
    punch_item = "punch_item"
    defect = "defect"
    submittal = "submittal"
    change_order = "change_order"
    co_candidate = "co_candidate"


class InboxBucket(StrEnum):
    assigned_to_me = "assigned_to_me"
    awaiting_review = "awaiting_review"


class InboxItem(BaseModel):
    """Compact per-item projection. The UI drills via `deep_link` for the
    full record on the module's own page — the inbox is a triage view,
    not a working surface."""

    model_config = ConfigDict(from_attributes=True)
    kind: InboxItemKind
    bucket: InboxBucket
    id: UUID
    project_id: UUID | None = None
    project_name: str | None = None
    # Free-form one-line title (RFI subject / punch item description / etc.)
    title: str
    # Optional secondary line (e.g. CO number, severity, ball-in-court).
    subtitle: str | None = None
    status: str | None = None
    severity: str | None = None
    due_date: date | None = None
    created_at: datetime | None = None
    deep_link: str  # e.g. "/drawbridge#rfi=<uuid>" — UI resolves


class InboxBucketSummary(BaseModel):
    bucket: InboxBucket
    count: int


class InboxResponse(BaseModel):
    items: list[InboxItem] = Field(default_factory=list)
    summary: list[InboxBucketSummary] = Field(default_factory=list)
    total: int
