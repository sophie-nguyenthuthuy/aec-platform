"""Schemas for the webhook subscription + delivery endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


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
    back. If they lose it, they rotate by deleting + recreating.

    Rotation status fields (cycle P1) are computed at read time from
    the `secret_previous` + `secret_previous_expires_at` model columns:

      * `secret_previous_active` — bool. True iff a rotation is in
        flight AND the grace window hasn't expired. The dispatcher
        uses the same condition (`_previous_secret_active`) to decide
        whether to emit `X-AEC-Signature-Previous`; surfacing it here
        means the partner UI shows the same answer the wire is
        seeing.
      * `secret_previous_grace_seconds_remaining` — int seconds
        until the grace window closes, or 0 when not in a grace.
        Frontend renders this as "rotation grace ends in 14h" so
        the partner knows how long they have to roll their receiver.

    Both are NEVER persisted — they're computed in
    `_attach_rotation_status` from the raw model columns at validation
    time. Removing the model columns would silently set both to
    False/0 (defensive); pinning the contract via the integrator
    surface snapshot prevents that drift."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    url: str
    event_types: list[str]
    enabled: bool
    last_delivery_at: datetime | None
    failure_count: int
    created_at: datetime
    # ---------- Rotation status (computed) ----------
    secret_previous_active: bool = False
    secret_previous_grace_seconds_remaining: int = 0

    @model_validator(mode="before")
    @classmethod
    def _attach_rotation_status(cls, data: Any) -> Any:
        """Compute the two rotation-status fields from the model's
        `secret_previous_expires_at` column.

        Runs in `mode="before"` because the input is either:
          * an ORM `WebhookSubscription` (when called via
            `model_validate(orm_row)`) — we read attributes;
          * a dict (when called via `model_validate(dict)`) — we
            read keys.

        Either way, the computed pair gets written into the dict the
        rest of validation sees, so the public-facing fields surface
        on `model_dump()`. The raw columns themselves are never
        copied into the projection — the dict only learns the
        derived booleans + integer.

        Why a model_validator vs. computed_field: computed_field is
        cleaner but recomputes on every dump; we want the value
        captured at projection time so a list response doesn't drift
        across rows mid-render. The bound copy also makes the JSON
        time-stable even if a list is dumped twice in the same
        request.
        """

        # Helper that handles both ORM-row + dict input shapes.
        def _read(obj: Any, key: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        expires_at = _read(data, "secret_previous_expires_at")
        secret_previous = _read(data, "secret_previous")
        active, remaining = _compute_rotation_status(
            secret_previous=secret_previous,
            expires_at=expires_at,
        )

        # Mutate the dict in-place when possible. For ORM rows we
        # build a shallow dict — Pydantic's `from_attributes=True`
        # accepts dicts on the input side, so this is the lighter
        # touch than constructing a new model.
        if isinstance(data, dict):
            data.setdefault("secret_previous_active", active)
            data.setdefault("secret_previous_grace_seconds_remaining", remaining)
            return data

        # ORM row path. Build a dict that carries every attribute
        # the schema declares + the two computed ones. Walking
        # `model_fields` keeps us robust to reorder.
        out: dict[str, Any] = {}
        for field_name in cls.model_fields:
            if field_name in (
                "secret_previous_active",
                "secret_previous_grace_seconds_remaining",
            ):
                continue
            out[field_name] = getattr(data, field_name, None)
        out["secret_previous_active"] = active
        out["secret_previous_grace_seconds_remaining"] = remaining
        return out


def _compute_rotation_status(
    *,
    secret_previous: str | None,
    expires_at: datetime | None,
) -> tuple[bool, int]:
    """Pure helper: derive (active, remaining_seconds) from the two
    raw model columns.

    Mirrors `services.webhooks._previous_secret_active` semantics —
    the wire-side dispatcher and the read-side projection MUST agree
    or the partner UI shows "grace active" while the dispatcher has
    stopped emitting the second header (or vice versa). Same three
    guards documented there.

    Returns `(False, 0)` for any case the dispatcher would treat as
    inactive (no rotation, expiry unset, expiry past). For the active
    case, the integer is `max(0, expires_at - now)` in seconds —
    `max(0, ...)` defends against a clock skew where the helper
    returns active=True but expires_at is technically a microsecond
    behind `now`.
    """
    if not secret_previous or expires_at is None:
        return (False, 0)
    now = datetime.now(UTC)
    if expires_at <= now:
        return (False, 0)
    delta = expires_at - now
    return (True, max(0, int(delta.total_seconds())))


class WebhookSubscriptionCreated(WebhookSubscriptionOut):
    """One-time response shape for `POST /webhooks` — includes the
    secret so the customer can paste it into their receiver. Listing
    endpoints use the bare `WebhookSubscriptionOut` instead."""

    secret: str


class WebhookDeliveryOut(BaseModel):
    """Read-side projection used by `/webhooks/{id}/deliveries` AND
    `/webhooks/deliveries/dead-letter`. The dead-letter feed reuses
    this shape across subscriptions, so `subscription_id` is required
    — pinned by `tests/test_integrator_surface_snapshot.py`."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    subscription_id: UUID
    event_type: str
    status: str
    attempt_count: int
    response_status: int | None
    response_body_snippet: str | None
    error_message: str | None
    delivered_at: datetime | None
    created_at: datetime
    payload: dict[str, Any]
