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
    # Joined at read time from `users.email`. Populated only for
    # human actors (where `actor_user_id` is non-NULL). NULL for
    # api-key + system rows.
    actor_email: str | None = None
    # Joined at read time from `api_keys.name`. Populated only for
    # api-key actors (where `actor_api_key_id` is non-NULL). The UI
    # renders this with a "key" badge so partner integrations are
    # visually distinct from human actions.
    actor_api_key_name: str | None = None
    action: str
    resource_type: str
    resource_id: UUID | None
    before: dict[str, Any]
    after: dict[str, Any]
    ip: str | None
    user_agent: str | None
    created_at: datetime
