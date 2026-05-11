"""ORM model for `cron_runs` — telemetry the arq cron decorator
writes on every invocation.

See migration `0042_cron_runs.py` for the schema rationale (one row
per invocation, indexed by (cron_name, started_at DESC), 'running'
state for long-jobs).

Lives in its own file (not appended to `models/core.py`) for the
same recurring rationale: the linter pass historically targets
`models/core.py` and a separate file dodges that.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from models.core import TZ  # type: ignore[attr-defined]


class CronRun(Base):
    """One row per arq cron invocation. Written by
    `services.cron_telemetry.cron_telemetry_wrap` at start AND
    finish — the row is INSERTed in `running` status when the
    coroutine begins, then UPDATEd to `succeeded` / `failed` when
    it returns / raises.

    Why update-in-place rather than two rows:
      * The dashboard's "currently running" view needs to find
        `running` rows that haven't finished. With two rows
        (started + finished) the join is awkward.
      * The natural shape is "one invocation = one row" — same
        idiom as `import_jobs`.
    """

    __tablename__ = "cron_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    cron_name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    # 'running' | 'succeeded' | 'failed'. Closed vocabulary lives in
    # services/cron_telemetry.py::CronRunStatus — adding a value
    # there + bumping this comment is the only place to change.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
