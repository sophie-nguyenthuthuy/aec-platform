"""Pydantic schemas for the no-auth supplier RFQ-response portal.

Distinct from `schemas.costpulse.RfqOut` because:

  * The portal exposes a strictly-narrower view than the dashboard does
    (no internal IDs, no other suppliers, no internal estimate metadata).
  * Field naming is supplier-friendly ("project" not "project_id",
    plain dates not ISO timestamps where the supplier doesn't care).
  * The response submission form is a different shape than what the
    dashboard already accepts via `RfqOut.responses[]`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicBoqLine(BaseModel):
    """One line of the BOQ digest the supplier sees on the response page.

    Identifiers are intentionally absent — the supplier doesn't need them
    and we don't want the public surface area carrying internal UUIDs.
    """

    description: str
    material_code: str | None = None
    quantity: float | None = None
    unit: str | None = None


class PublicRfqContext(BaseModel):
    """Everything the supplier sees on `GET /api/v1/public/rfq/context`."""

    organization_name: str
    """Display name of the buyer org. The only place we surface tenant
    identity to a non-authenticated party."""

    project_name: str | None = None
    estimate_name: str | None = None
    deadline: date | None = None
    message: str | None = None
    boq_digest: list[PublicBoqLine] = Field(default_factory=list)

    submission_status: Literal["pending", "submitted"]
    """`pending` = supplier hasn't quoted yet. `submitted` = a quote is
    already on file for this token; the response form is hidden."""

    submitted_quote: PublicRfqQuote | None = None
    """When `submission_status == "submitted"`, this echoes back the
    supplier's previous submission so they can confirm what they sent."""


class PublicRfqQuote(BaseModel):
    """The shape suppliers POST to `/api/v1/public/rfq/respond`.

    Quantities and lead times are optional because some suppliers
    respond to a high-level RFQ with just a top-line number; others
    fill in line-by-line. We let the dashboard render either.
    """

    model_config = ConfigDict(extra="forbid")

    total_vnd: Decimal | None = None
    """Top-line quoted total. None if the supplier only filled lines."""

    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    line_items: list[PublicRfqQuoteLine] = Field(default_factory=list)


class PublicRfqQuoteLine(BaseModel):
    """One line in a per-item quote."""

    model_config = ConfigDict(extra="forbid")

    material_code: str | None = None
    """Match against the buyer's BOQ when present; otherwise free-text."""

    description: str
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    unit_price_vnd: Decimal | None = Field(default=None, ge=0)


# Pydantic v2 needs explicit forward-ref rebuild for the self-referential
# `submitted_quote` field on PublicRfqContext.
PublicRfqContext.model_rebuild()
