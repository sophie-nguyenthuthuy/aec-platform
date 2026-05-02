"""ORM model for the `api_keys` table.

See migration 0031_api_keys for the schema rationale (why we hash at
rest, why `prefix` exists, why scopes are an open text array).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, PrimaryKeyConstraint, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.core import TZ  # type: ignore[attr-defined]


class ApiKey(Base):
    """Per-org programmatic credential. Plaintext key is never
    persisted; we keep `hash` (sha256-hex) + `prefix` (first 8 chars
    for UI disambiguation)."""

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)
    last_used_at: Mapped[datetime | None] = mapped_column(TZ)
    last_used_ip: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    expires_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ApiKeyCall(Base):
    """Per-minute call counter, one row per (api_key, minute, success).

    Composite PK matches the ON CONFLICT clause in
    `services.api_keys.record_call`. Migration 0032_api_key_calls
    carries the schema rationale (why we don't carry organization_id
    here, why minute granularity, etc.).
    """

    __tablename__ = "api_key_calls"

    api_key_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    minute_bucket: Mapped[datetime] = mapped_column(TZ, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (PrimaryKeyConstraint("api_key_id", "minute_bucket", "success", name="pk_api_key_calls"),)
