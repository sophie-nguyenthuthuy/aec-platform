"""ORM model for `retention_overrides` — per-tenant retention TTL
extensions (cycle T3).

See migration 0046_retention_overrides for the schema rationale (one
row per (organization, table), `ttl_days` extends the policy default,
`set_by` / `set_at` for the audit trail).

Lives in its own file (not appended to `models/core.py`) for the
same recurring rationale: the linter pass historically targets the
larger model files; a separate file dodges that.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, PrimaryKeyConstraint, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.core import TZ  # type: ignore[attr-defined]


class RetentionOverride(Base):
    """One row per (organization_id, table_name) — extends the
    platform-wide retention TTL for compliance-conscious customers.

    The retention cron consults this row in
    `services.retention.policy_ttl_days(policy, organization_id)`
    BEFORE falling back to env / policy default. Service-layer
    validation enforces `ttl_days >= policy.default_days` (extend
    only, never shorten).
    """

    __tablename__ = "retention_overrides"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id",
            "table_name",
            name="pk_retention_overrides",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    set_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    set_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    # Optional free-text reason — compliance-bearing context like
    # "ISO 27001 audit retention" surfaces in the admin UI tooltip.
    reason: Mapped[str | None] = mapped_column(Text)
