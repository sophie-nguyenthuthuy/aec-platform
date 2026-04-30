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
    actor_email: str | None = None  # joined from users table at read time
    action: str
    resource_type: str
    resource_id: UUID | None
    before: dict[str, Any]
    after: dict[str, Any]
    ip: str | None
    user_agent: str | None
    created_at: datetime
