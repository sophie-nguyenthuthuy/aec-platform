"""Wrap an arq cron coroutine with `cron_runs` telemetry.

Usage in `workers/queue.py`:

    from services.cron_telemetry import cron_telemetry_wrap

    cron_jobs = [
        cron(cron_telemetry_wrap(weekly_report_cron), weekday="mon", ...),
        ...
    ]

The wrapper:

  1. Inserts a `cron_runs` row in `running` status BEFORE the body
     runs. Captures the row id so the finish-time UPDATE writes back
     to the same row (avoids races between concurrent crons).

  2. Runs the original coroutine. Catches every exception so the
     cron's failure can be recorded — re-raises after writing the
     row so arq still sees the error and applies its own retry
     policy.

  3. UPDATEs the row to `succeeded` / `failed` with `finished_at`,
     `duration_ms`, and (on failure) the error message truncated
     to 2000 chars.

Why a wrapper rather than a middleware on the worker:
  * arq doesn't have request/response middleware in the FastAPI sense.
  * A wrapper keeps the change LOCAL to the cron registration, so
    rolling out per-cron is a one-line edit.
  * The wrapped function preserves `__name__` + docstring so
    `routers/cron_admin.py::list_crons` (which reads
    `coro.__name__` for the function-name column) keeps working.

Why best-effort writes:
  * Telemetry that crashes the worker is worse than no telemetry —
    if the cron_runs INSERT fails (DB outage), we log + run the
    body anyway. Same posture as `services.api_keys.record_call`.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text

from db.session import AdminSessionFactory

logger = logging.getLogger(__name__)


# Closed status vocabulary. Mirrors the comment in models/cron_run.py
# — adding a value here means the dashboard's status renderer also
# needs the new case. Pinned by the integrator-surface snapshot.
CronRunStatus = str  # "running" | "succeeded" | "failed"


# Cap on stored error_message. Avoids an exotic traceback bloating the
# table; 2000 chars is enough for the first frame + module path
# (operators chase the rest in the worker logs anyway).
_MAX_ERROR_MESSAGE_LEN = 2000


async def _record_start(cron_name: str) -> UUID | None:
    """INSERT a 'running' row, return its id. Returns None on DB
    failure — the caller should still run the cron body in that case
    (see `cron_telemetry_wrap`'s try/except)."""
    try:
        async with AdminSessionFactory() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO cron_runs (cron_name, status)
                    VALUES (:cron_name, 'running')
                    RETURNING id
                    """
                ),
                {"cron_name": cron_name},
            )
            row_id = result.scalar_one()
            await session.commit()
            return row_id  # type: ignore[no-any-return]
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "cron_telemetry: failed to record start for %s (%s); skipping telemetry",
            cron_name,
            exc,
        )
        return None


async def _record_finish(
    run_id: UUID,
    *,
    status: str,
    duration_ms: int,
    error_message: str | None,
) -> None:
    """UPDATE the previously-inserted row with finish-time fields.
    Best-effort: a failed UPDATE here only loses the telemetry, not
    the cron's actual work."""
    try:
        async with AdminSessionFactory() as session:
            await session.execute(
                text(
                    """
                    UPDATE cron_runs
                    SET finished_at = NOW(),
                        status = :status,
                        duration_ms = :duration_ms,
                        error_message = :error_message
                    WHERE id = :id
                    """
                ),
                {
                    "id": str(run_id),
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_message": error_message,
                },
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "cron_telemetry: failed to record finish for run %s (%s)",
            run_id,
            exc,
        )


def cron_telemetry_wrap(
    coroutine: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Wrap an arq cron coroutine to write `cron_runs` telemetry.

    Returns a coroutine with the SAME `__name__`, `__module__`, and
    `__doc__` as the input — `routers/cron_admin.py::list_crons`
    reads those for the dashboard table, so preserving them is part
    of the contract.

    The wrapper accepts the same `(ctx)` signature arq passes to
    every cron. On failure it re-raises so arq's retry/error logging
    still sees the exception.

    Naming: the row's `cron_name` is `f"cron:{coroutine.__name__}"` —
    matches arq's auto-derived `CronJob.name`, so the dashboard can
    join on it. If arq's naming convention changes upstream, update
    `_cron_name_for` to match.
    """
    cron_name = _cron_name_for(coroutine)

    async def wrapper(ctx: dict[str, Any]) -> Any:
        run_id = await _record_start(cron_name)
        started = time.monotonic()
        try:
            result = await coroutine(ctx)
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            err = _truncate_error(exc)
            if run_id is not None:
                await _record_finish(
                    run_id,
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=err,
                )
            raise
        else:
            duration_ms = int((time.monotonic() - started) * 1000)
            if run_id is not None:
                await _record_finish(
                    run_id,
                    status="succeeded",
                    duration_ms=duration_ms,
                    error_message=None,
                )
            return result

    # Preserve metadata so the cron-registry dashboard reads the right
    # function name / module / docstring. functools.wraps would also
    # work but explicit is clearer for the few attributes that matter.
    wrapper.__name__ = coroutine.__name__
    wrapper.__module__ = coroutine.__module__
    wrapper.__doc__ = coroutine.__doc__
    wrapper.__qualname__ = coroutine.__qualname__
    # `__wrapped__` is the standard `functools.wraps` convention and
    # lets `inspect.getsource(inspect.unwrap(handler))` pull the
    # original cron's source. The cron-mutex audit relies on this to
    # see the `# cron-mutex: …` annotations declared inside the cron
    # body — without it the audit reads `wrapper`'s source and every
    # cron looks unsafe.
    wrapper.__wrapped__ = coroutine  # type: ignore[attr-defined]
    # arq inspects the signature when registering the cron; preserve
    # so kwargs-based scheduling (`cron(coro, hour=1)`) doesn't get
    # surprised by a different signature on the wrapper. Some
    # lambdas / built-ins won't introspect cleanly — `suppress`
    # tolerates that and arq falls back to its own duck-typing.
    with contextlib.suppress(TypeError, ValueError):
        wrapper.__signature__ = inspect.signature(coroutine)  # type: ignore[attr-defined]
    return wrapper


def _cron_name_for(coroutine: Callable[..., Awaitable[Any]]) -> str:
    """Match arq's `CronJob.name` shape. arq uses `f"cron:{coro.__name__}"`
    — keep the format aligned so dashboard joins on cron_name work."""
    return f"cron:{coroutine.__name__}"


def _truncate_error(exc: BaseException) -> str:
    """Format and truncate the error message for storage. We store a
    single line (the exception's str()) rather than the full
    traceback — operators chase the traceback in worker logs; the
    DB row exists to flag "this cron is failing" not to be the
    primary debugging artefact."""
    msg = f"{type(exc).__name__}: {exc}"
    if len(msg) > _MAX_ERROR_MESSAGE_LEN:
        return msg[: _MAX_ERROR_MESSAGE_LEN - 1] + "…"
    return msg


# ---------- Read-side helpers (used by routers/cron_admin.py) ----------


async def latest_run_per_cron() -> dict[str, dict[str, Any]]:
    """Return one row per `cron_name` — the most recent run, plus a
    `stuck` boolean for currently-running rows.

    Used by the `/admin/crons` dashboard to attach last-run metadata
    to the static registry. Crons that haven't fired yet have no
    entry in the result; the caller renders them as "(no runs yet)".

    `stuck` is True iff the row is `running` AND elapsed > 3× the
    cron's rolling 7d p95 (decision delegated to
    `services.cron_alerts._is_stuck` so dashboard + watchdog use
    the same rule). For non-running rows `stuck` is None.

    Why DISTINCT ON: the (cron_name, started_at DESC) index makes
    this an index-only scan — no in-memory sort. PG-specific but
    we're already PG-only across the platform.
    """
    sql = text(
        """
        SELECT DISTINCT ON (cron_name)
            cron_name, started_at, finished_at, status,
            duration_ms, error_message,
            -- Elapsed-so-far for running rows. Lets the caller
            -- compute `stuck` without a second round-trip.
            CASE WHEN status = 'running'
                 THEN EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
                 ELSE NULL
            END AS elapsed_ms
        FROM cron_runs
        ORDER BY cron_name, started_at DESC
        """
    )
    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql)).mappings().all()

    p95_by_name = await _p95_per_cron()

    # Lazy import — `cron_alerts._is_stuck` is a pure helper but the
    # module imports `slack_telemetry` lazily for the alerter path.
    # Importing at module-load would force every cron-telemetry caller
    # to load the Slack stack.
    from services.cron_alerts import _is_stuck

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cron_name = r["cron_name"]
        is_running = r["status"] == "running"
        stuck: bool | None = None
        if is_running:
            baseline = p95_by_name.get(cron_name)
            stuck = _is_stuck(
                {
                    "elapsed_ms": r["elapsed_ms"],
                    "sample_count": baseline.get("sample_count") if baseline else None,
                    "p95_ms": baseline.get("p95_ms") if baseline else None,
                }
            )
        out[cron_name] = {
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": (r["finished_at"].isoformat() if r["finished_at"] else None),
            "status": r["status"],
            "duration_ms": r["duration_ms"],
            "error_message": r["error_message"],
            "stuck": stuck,
        }
    return out


async def _p95_per_cron() -> dict[str, dict[str, Any]]:
    """Rolling 7d p95 + sample_count per cron_name. Helper for the
    stuck-detection join in `latest_run_per_cron`.

    Same window as `services.cron_alerts._BASELINE_WINDOW_DAYS` —
    the two MUST match for the dashboard's `stuck` flag to align
    with the watchdog's alert decision. Different values would mean
    the dashboard says "stuck" when the watchdog wouldn't have
    alerted, or vice versa — confusing for ops.
    """
    sql = text(
        """
        SELECT
            cron_name,
            COUNT(*) AS sample_count,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                AS p95_ms
        FROM cron_runs
        WHERE status = 'succeeded'
          AND duration_ms IS NOT NULL
          AND started_at >= NOW() - INTERVAL '7 days'
        GROUP BY cron_name
        """
    )
    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql)).mappings().all()
    return {r["cron_name"]: {"sample_count": r["sample_count"], "p95_ms": r["p95_ms"]} for r in rows}


async def recent_runs_for_cron(cron_name: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return the N most recent runs for one cron, newest first.

    Drives the per-cron sparkline / recent-runs panel. Capped at 20
    by default — the index is keyed on (cron_name, started_at DESC)
    so this is an O(log n + limit) lookup.
    """
    sql = text(
        """
        SELECT id, started_at, finished_at, status, duration_ms, error_message
        FROM cron_runs
        WHERE cron_name = :cron_name
        ORDER BY started_at DESC
        LIMIT :limit
        """
    )
    async with AdminSessionFactory() as session:
        rows = (await session.execute(sql, {"cron_name": cron_name, "limit": limit})).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": (r["finished_at"].isoformat() if r["finished_at"] else None),
            "status": r["status"],
            "duration_ms": r["duration_ms"],
            "error_message": r["error_message"],
        }
        for r in rows
    ]


__all__ = [
    "CronRunStatus",
    "cron_telemetry_wrap",
    "latest_run_per_cron",
    "recent_runs_for_cron",
]


# `asyncio` is imported defensively for completeness even though the
# wrappers here go through AdminSessionFactory (which already ties
# into the running loop). Keeps the module self-contained for the
# rare ad-hoc test that constructs a wrapper out-of-band.
_ = asyncio
