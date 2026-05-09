"""Schemas for the audit-log read endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    actor_user_id: UUID | None
    actor_api_key_id: UUID | None = None
    # Joined at read time: users.email for human actors, or
    # `api_key:<name>` for api-key actors. NULL for cron / system rows.
    actor_email: str | None = None
    action: str
    resource_type: str
    resource_id: UUID | None
    before: dict[str, Any]
    after: dict[str, Any]
    ip: str | None
    user_agent: str | None
    created_at: datetime
