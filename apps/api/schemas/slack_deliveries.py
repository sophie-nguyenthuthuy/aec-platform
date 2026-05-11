"""Pydantic schemas for the Slack-deliveries admin surface.

Lives in its own file (rather than `schemas/admin.py`) so the
revert pattern targeting `schemas/admin.py` doesn't take this
surface down with it. The matching admin router
(`routers/slack_deliveries.py`) imports from here directly; no
re-export through `schemas/admin.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SlackDeliveryOut(BaseModel):
    """One row from `slack_deliveries`. Mirrors `models.slack_delivery.SlackDelivery`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    delivered: bool
    reason: str | None = None
    status_code: int | None = None
    text_preview: str = ""
    created_at: datetime


class SlackDeliveriesSummaryRow(BaseModel):
    """Per-`kind` rollup for the `/admin/slack-deliveries` dashboard.

    `delivered_rate` is the success ratio over the window — `None`
    when the window had zero attempts (no data, NOT zero%). The
    frontend distinguishes those: null = "no data", zero =
    "ops, fix this now."
    """

    kind: str
    total_attempts: int
    delivered_count: int
    failed_count: int
    delivered_rate: float | None = Field(default=None, ge=0, le=1)
    last_attempt_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_reason: str | None = None
