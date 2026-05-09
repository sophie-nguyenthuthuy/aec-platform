"""Schemas for the webhook subscription + delivery endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class WebhookSubscriptionCreate(BaseModel):
    url: HttpUrl
    # Empty list = subscribe to ALL events. List of dotted slugs (same
    # vocabulary as `services/audit.AuditAction` plus a few non-audit
    # ones registered in `services/webhooks._WEBHOOK_EVENT_TYPES`)
    # otherwise.
    event_types: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("event_types")
    @classmethod
    def _validate_event_types(cls, v: list[str]) -> list[str]:
        # Bound the per-event-type length so a typo doesn't blow up the
        # array column.
        for item in v:
            if not item or len(item) > 80:
                raise ValueError(f"invalid event_type: {item!r}")
            # The convention is `module.resource.verb` but we don't
            # enforce a hard regex — the dispatcher matches by literal
            # equality so adding a new event type is a 1-line PR.
        return v


class WebhookSubscriptionUpdate(BaseModel):
    enabled: bool | None = None
    event_types: list[str] | None = Field(default=None, max_length=50)


class WebhookSubscriptionOut(BaseModel):
    """Public projection. **Never** includes `secret` — the customer
    sees the secret exactly once at creation time and we never echo it
    back. If they lose it, they rotate by deleting + recreating."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    url: str
    event_types: list[str]
    enabled: bool
    last_delivery_at: datetime | None
    failure_count: int
    created_at: datetime


class WebhookSubscriptionCreated(WebhookSubscriptionOut):
    """One-time response shape for `POST /webhooks` — includes the
    secret so the customer can paste it into their receiver. Listing
    endpoints use the bare `WebhookSubscriptionOut` instead."""

    secret: str


class WebhookDeliveryOut(BaseModel):
    """Read-side projection used by `/webhooks/{id}/deliveries`."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    status: str
    attempt_count: int
    response_status: int | None
    response_body_snippet: str | None
    error_message: str | None
    delivered_at: datetime | None
    created_at: datetime
    payload: dict[str, Any]
