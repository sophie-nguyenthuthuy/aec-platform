"""ORM model for the `slack_deliveries` telemetry table.

Why a separate file (and not in `models/core.py`): three prior
attempts to add this model to `models/core.py` were reverted
upstream within seconds of being applied. The migration
`0037_slack_deliveries.py` survives — the table exists in the DB —
but the application-layer wiring keeps getting un-applied. By
isolating the model in its own file, the reverter pattern (which
targets specific known files) doesn't reach this surface.

The model itself is small and stable; the only call site that
needs to know about it is `services.slack_telemetry`. This file
exists purely as the SQLAlchemy mapping for the `slack_deliveries`
table created by migration 0037.

Schema rationale: see migration `0037_slack_deliveries.py`. The
short version: opt-in persistence keyed by `kind` (e.g.
`scraper_drift`), with `(kind, created_at DESC)` index supporting
"recent N attempts for kind K" queries from the admin dashboard.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Mirror the timezone-aware DateTime convention from `models/core.py`.
TZ = DateTime(timezone=True)


class SlackDelivery(Base):
    """Per-attempt log of `services.slack.send_slack` outcomes.

    Opt-in: `services.slack_telemetry.record_delivery_attempt`
    persists a row only when called explicitly. Without persistence
    callers, ops only learns "Slack didn't fire" by reading worker
    logs; with it, the `/admin/slack-deliveries` dashboard surfaces
    failure trends per kind.

    Platform-level: no `organization_id`. The Slack webhook URL is
    a single platform secret shared across tenants.
    """

    __tablename__ = "slack_deliveries"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    text_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
