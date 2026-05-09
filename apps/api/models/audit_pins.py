"""ORM model for `audit_pins` — admin-pinned audit_events (cycle U3).

See migration 0047_audit_pins for the schema rationale (PK on
`(audit_event_id, pinned_by)`, FK CASCADE on both columns so
deleting a user OR an audit row drops the orphan pin).

Lives in its own file (not appended to `models/audit.py`) for the
same recurring rationale as `models/cron_run.py` etc — separate file
dodges aggressive linter passes that target the larger model files.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, PrimaryKeyConstraint, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.core import TZ  # type: ignore[attr-defined]


class AuditPin(Base):
    """Admin's bookmark on one audit_events row.

    Lifecycle:
      * INSERT'd by `POST /api/v1/audit/events/{id}/pin`.
      * DELETE'd by `DELETE /api/v1/audit/events/{id}/pin`.
      * CASCADE-dropped if the audit row OR the user is deleted.

    The frontend's audit listing reads pinned rows for the current
    user via a JOIN; pinned rows always render at top regardless
    of pagination state.
    """

    __tablename__ = "audit_pins"
    __table_args__ = (PrimaryKeyConstraint("audit_event_id", "pinned_by", name="pk_audit_pins"),)

    audit_event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audit_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    pinned_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    pinned_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    # Optional reviewer note (e.g. "smoking gun for outage 2026-05-01").
    # 500-char cap mirrors the audit reason idiom.
    note: Mapped[str | None] = mapped_column(Text)
