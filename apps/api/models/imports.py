"""ORM model for the `import_jobs` table.

Backs the `/settings/import` page's two-phase upload: a `preview`
request creates a row in `previewed` state with the parsed `rows` and
per-row `errors`, and a separate `commit` call upserts the validated
rows into the target entity table and stamps `committed_count` +
`committed_at`. Migration 0029 carries the rationale.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.core import TZ  # type: ignore[attr-defined]


class ImportJob(Base):
    """One row per CSV/XLSX upload. The `rows` and `errors` JSONB
    columns hold the parsed payload between preview and commit; for V1
    we cap uploads at 1000 rows so the JSONB blob stays small."""

    __tablename__ = "import_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="previewed")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rows: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    committed_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    committed_at: Mapped[datetime | None] = mapped_column(TZ)
