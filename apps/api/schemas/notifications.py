"""Schemas for the notifications module — project watches + daily digests."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProjectWatchCreate(BaseModel):
    project_id: UUID


class ProjectWatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    user_id: UUID
    project_id: UUID
    created_at: datetime


class WatchedProject(BaseModel):
    """List item: combines the watch row + denormalized project name so
    the UI can render "Tower A — watching since 2026-04-26" without a
    follow-up fetch."""

    watch_id: UUID
    project_id: UUID
    project_name: str
    created_at: datetime


# ---------- Notification preferences ----------


class NotificationPreferenceOut(BaseModel):
    """Per-user, per-org opt-in for an alert `key`."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    key: str
    email_enabled: bool
    slack_enabled: bool
    updated_at: datetime


class NotificationPreferenceUpdate(BaseModel):
    """Both channel flags are optional; omit one to leave it unchanged.

    PUT-shaped (idempotent overwrite of the requested fields) rather
    than PATCH so the two UI checkboxes can each fire independently
    without an unstable interleaving of partial PATCHes.
    """

    email_enabled: bool | None = None
    slack_enabled: bool | None = None
