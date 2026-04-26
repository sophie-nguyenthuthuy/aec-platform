"""ChangeOrder extensions — sources, line items, approval workflow, AI candidates.

The base `change_orders` table already exists in `pulse.py` (number, title,
status, cost_impact_vnd, schedule_impact_days, ai_analysis JSONB). This module
adds the structured supporting tables that the AI pipeline needs:

  * `change_order_sources` — links a CO back to whatever surfaced it: an RFI,
    a daily-log observation, an inbound email, or "manual". Multi-source is
    legal because complex COs often emerge from a thread of triggers.
  * `change_order_line_items` — breakdown for cost/schedule impact. The
    parent CO's `cost_impact_vnd` becomes the SUM(line_items.cost_vnd)
    once a line item exists; before that, the lump-sum value on the parent
    is the source of truth (so a quick draft doesn't require a line item).
  * `change_order_approvals` — append-only audit trail of state transitions
    (submitted → reviewed → approved / rejected, by whom, when, with notes).
  * `change_order_candidates` — AI-suggested CO drafts produced from RFIs
    or pasted emails. Persisted so the user can accept/reject them; an
    accepted candidate creates a real CO and stamps `accepted_co_id`.

Cross-module hooks:
  * `source_rfi_id` (drawbridge.rfis)
  * `source_observation_id` (daily_log_observations) — when a SiteEye safety
    hit or a daily-log issue cascades into a real change.
  * `schedule_activity_id` on line items — pin a time-impact line item to a
    specific SchedulePilot activity.
  * Cost line items map to CostPulse via free-form spec_section text (no
    hard FK; CostPulse keys on price catalog rows that change frequently).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

TZ = DateTime(timezone=True)


class ChangeOrderSource(Base):
    """One row per upstream trigger. A CO can have multiple sources."""

    __tablename__ = "change_order_sources"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    # rfi | observation | email | manual | external
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    rfi_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("rfis.id", ondelete="SET NULL"))
    observation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("daily_log_observations.id", ondelete="SET NULL"),
    )
    # Free-form payload — for emails: subject + body excerpt; for external
    # references: a URL or doc title.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ChangeOrderLineItem(Base):
    """Itemized breakdown for cost & schedule impact."""

    __tablename__ = "change_order_line_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # add | delete | substitute
    line_kind: Mapped[str] = mapped_column(Text, nullable=False, default="add")
    # Free-form CSI spec_section so we can correlate to CostPulse without
    # a hard FK against a price catalog that mutates frequently.
    spec_section: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    unit_cost_vnd: Mapped[int | None] = mapped_column(BigInteger)
    cost_vnd: Mapped[int | None] = mapped_column(BigInteger)
    # Per-item time impact, in days. Sum may NOT equal parent
    # `schedule_impact_days` if items run in parallel — the AI analyzer is
    # responsible for the rollup.
    schedule_impact_days: Mapped[int | None] = mapped_column(Integer)
    schedule_activity_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule_activities.id", ondelete="SET NULL"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ChangeOrderApproval(Base):
    """Append-only state-transition log. The latest row's `to_status` should
    match the CO's `status` column. Useful for compliance audits and for
    showing "who approved CO-007 and when?" in the UI."""

    __tablename__ = "change_order_approvals"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Whatever status was on the CO before this row was inserted.
    from_status: Mapped[str | None] = mapped_column(Text)
    # draft | submitted | reviewed | approved | rejected | executed | cancelled
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ChangeOrderCandidate(Base):
    """LLM-suggested CO drafts produced from an RFI or pasted email.

    `accepted_co_id` is null until a user promotes the candidate; once
    promoted, the candidate becomes immutable history. Rejecting the
    candidate sets `rejected_at` (still keeping the row for audit).
    """

    __tablename__ = "change_order_candidates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # rfi | email | manual_paste
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_rfi_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("rfis.id", ondelete="SET NULL"))
    source_text_snippet: Mapped[str | None] = mapped_column(Text)
    # The LLM's structured proposal:
    #   { title, description, line_items: [...], cost_impact_vnd_estimate,
    #     schedule_impact_days_estimate, confidence_pct, rationale }
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_co_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("change_orders.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    rejected_at: Mapped[datetime | None] = mapped_column(TZ)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
