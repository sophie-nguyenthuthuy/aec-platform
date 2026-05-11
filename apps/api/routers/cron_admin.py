"""Platform-admin endpoint for the cron-job registry.

Exposes the static list of arq cron jobs (`workers.queue.WorkerSettings.cron_jobs`)
to the admin dashboard at `/admin/crons` so an operator can see at a
glance what the worker is supposed to run, on what schedule, and
when each is next due.

Lives in its OWN file (not appended to `routers/admin.py`) for the
same reason the slack_deliveries + webhook_deliveries_admin routers
are split out: an aggressive linter pass historically reverts adds to
`routers/admin.py` within seconds. Separate file dodges that.

What this endpoint INTENTIONALLY doesn't return (v1 scope):

  * Per-cron last-run telemetry. arq stores recent `JobResult` records
    in Redis but with a short TTL (`keep_result_s` = 3600s by default
    in this codebase). Surfacing "last run" reliably needs either a
    persisted `cron_runs` audit table OR a Redis read on every page
    load with the caveat "anything older than an hour is gone." Both
    are follow-up work.

  * Status / health rollup. Without telemetry, "healthy" can't be
    derived. The page calls this out — listing the registry is
    valuable on its own (it's the source of truth for what a
    deployed worker should be running) even before health joins.

What this endpoint DOES return:

  * Cron name + module + function — one row per registered cron.
  * Human-readable schedule string ("Mondays 06:00 UTC", "Daily 22:00").
  * Next run timestamp (computed from the CronJob's calculate_next).
  * First line of the cron function's docstring as a description.

The data is in-process Python; no DB read required. Admin-role
gated like every other admin route.

Pinned by `tests/test_integrator_surface_snapshot.py` because the
frontend dashboard 404s if the route disappears.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from core.envelope import ok
from middleware.auth import AuthContext, require_role
from middleware.idempotency_route import IdempotentRoute

# `route_class=IdempotentRoute` so the manual-run POST honors
# `Idempotency-Key` — accidental double-clicks on the dashboard
# button don't enqueue two arq jobs. Read-only GETs are also wrapped
# but `IdempotentRoute.dispatch` short-circuits for safe methods.
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    route_class=IdempotentRoute,
)


# ---------- Schedule formatter ----------


_WEEKDAY_NAMES = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def _format_schedule(c: Any) -> str:
    """Turn an arq CronJob's (weekday, day, hour, minute) tuple into a
    human-readable string like "Mondays 06:00 UTC" or "Every minute".

    Conservative — covers the patterns currently in use in
    `WorkerSettings.cron_jobs` without trying to reverse-engineer
    every possible cron-spec edge case. New cron schedules that don't
    fit this format render as a fallback dump of the raw fields,
    which is still informative.
    """
    weekday = c.weekday
    day = c.day
    hour = c.hour
    minute = c.minute

    # `minute={0,1,...,59}` — every-minute pattern. Used by
    # `webhook_drain_cron`. The set comparison handles the explicit
    # range from the queue.py declaration.
    if isinstance(minute, set) and len(minute) == 60:
        return "Every minute"

    # Specific minute value — canonicalise to int for downstream
    # formatting. arq accepts {set, int, None}; we render only the
    # int branch precisely.
    minute_int = minute if isinstance(minute, int) else None
    hour_int = hour if isinstance(hour, int) else None

    parts: list[str] = []

    # Weekday → "Mondays at 06:00".
    if weekday is not None:
        if isinstance(weekday, str):
            parts.append(f"{_WEEKDAY_NAMES.get(weekday, weekday)}s")
        else:
            parts.append(f"weekday={weekday}")
    elif day is not None:
        parts.append(f"On day {day} of each month")
    else:
        parts.append("Daily")

    if hour_int is not None and minute_int is not None:
        parts.append(f"at {hour_int:02d}:{minute_int:02d} UTC")
    elif hour_int is not None:
        parts.append(f"hour={hour_int}")
    elif minute_int is not None:
        parts.append(f"minute={minute_int}")

    return " ".join(parts)


def _next_run_iso(c: Any) -> str | None:
    """Compute the next scheduled fire time (UTC ISO-8601) using arq's
    own `calculate_next`. Returns None if the underlying call raises —
    we'd rather render "—" than fail the whole list because of one
    bad cron entry."""
    try:
        # arq's calculate_next mutates the object's `next_run` field
        # to the next due time at OR after the passed-in datetime.
        # Pass `datetime.now(UTC)` so the result is the upcoming fire,
        # not the historical baseline.
        c.calculate_next(datetime.now(UTC))
        nxt = c.next_run
        if nxt is None:
            return None
        return nxt.isoformat()
    except Exception:
        return None


def _description_from_doc(coro: Any) -> str:
    """First line of the cron function's docstring. Truncated at 160
    chars so a chatty docstring doesn't wreck the table layout."""
    doc = (coro.__doc__ or "").strip()
    if not doc:
        return ""
    first_line = doc.splitlines()[0].strip()
    return first_line[:160] + ("…" if len(first_line) > 160 else "")


# ---------- Endpoint ----------


@router.get("/crons")
async def list_crons(
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Cron-job registry + last-run telemetry.

    Combines two sources:

      1. The in-process `WorkerSettings.cron_jobs` list — name,
         module, schedule, next_run. Same on every replica.

      2. Per-cron last-run row from `cron_runs` (joined by name) —
         status, duration, error_message. Crons that haven't fired
         yet have no entry; the page renders them as "no runs yet."

    The DB query is one DISTINCT ON over an indexed (cron_name,
    started_at DESC) — bounded at 10ish rows by the registry size,
    so it's effectively free.

    Sorted by next_run ASC NULLS LAST so the cron about to fire
    surfaces first; ops opening this page during an incident wants
    "what's running soon" up top.
    """
    from services.cron_telemetry import latest_run_per_cron
    from workers.queue import WorkerSettings

    last_runs = await latest_run_per_cron()

    rows: list[dict[str, Any]] = []
    for c in WorkerSettings.cron_jobs:
        coro = c.coroutine
        cron_name = c.name
        last = last_runs.get(cron_name)
        rows.append(
            {
                "name": cron_name,
                "function": coro.__name__,
                "module": coro.__module__,
                "schedule": _format_schedule(c),
                "next_run": _next_run_iso(c),
                "description": _description_from_doc(coro),
                "last_run": last,
            }
        )

    # Stable ordering: next_run ASC, NULLs last (None means
    # calculate_next failed; sink to bottom). Then by name for
    # determinism when two crons share the same minute.
    rows.sort(
        key=lambda r: (r["next_run"] is None, r["next_run"] or "", r["name"]),
    )

    return ok(rows)


@router.get("/crons/{cron_name}/runs")
async def list_cron_runs(
    cron_name: str,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Recent runs for one cron — newest first, capped at 20.

    Drives the per-cron drilldown / sparkline. Path param is the
    cron's full arq name (`cron:<function_name>`) so the URL matches
    what the list endpoint emits in `name`. Slash inside the name
    is fine — FastAPI's path resolution handles `cron:weekly_report`
    as a single segment.
    """
    from services.cron_telemetry import recent_runs_for_cron

    runs = await recent_runs_for_cron(cron_name, limit=20)
    return ok(runs)


# ---------- Manual run-now ----------


@router.post("/crons/{cron_name}/run", status_code=202)
async def run_cron_now(
    cron_name: str,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Enqueue an arq job that runs `cron_name` immediately.

    Closes the incident-triage loop: an operator looking at a failed
    cron on `/admin/crons/[name]` can re-run it without waiting for
    the next schedule tick or shelling into the worker. The arq job
    threads through `cron_telemetry_wrap` so the manual invocation
    writes a fresh `cron_runs` row — it shows up in the drilldown
    sparkline alongside scheduled runs, which is what the operator
    wants to see.

    Returns 202 with the arq job_id so the frontend can correlate the
    enqueue with the eventual `cron_runs` row (which has its own UUID
    — the job_id is incidental telemetry, not used for joining).

    Validation:

      * Unknown cron names 404. The lookup happens here AND inside
        the arq job (defense in depth: a cron added after the job
        was enqueued but before it runs would otherwise raise inside
        the job and burn an arq retry budget for nothing).

      * Admin-gated via `require_role("admin")` — this fires real
        side effects (S3 writes, downstream HTTP, downstream Slack).
        Only platform ops should be able to fire it.

    Audit: the `admin.cron.run_now` audit row carries the cron name
    and actor so "who manually ran X right before the outage?" stays
    answerable. (`record` is lazy-imported to avoid a heavy import at
    module load — same shape as the other admin handlers in this
    file.)
    """
    # Validate cron_name BEFORE enqueuing so a typo gets a 404 rather
    # than a queued-but-doomed job. The same lookup happens worker-
    # side as defense in depth.
    from workers.queue import WorkerSettings, get_pool

    if not any(c.name == cron_name for c in WorkerSettings.cron_jobs):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown cron_name: {cron_name!r}")

    pool = await get_pool()
    job = await pool.enqueue_job("run_cron_by_name_job", cron_name)
    if job is None:
        # arq returns None when a job with the same id is already
        # queued — shouldn't happen here (we don't pin _job_id) but
        # belt-and-braces.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Failed to enqueue manual cron run.",
        )

    # Audit AFTER enqueue: the row carries the actor + cron name +
    # arq job_id. Lazy import keeps the cron_admin module fast at
    # boot — the audit module pulls in services/notifications etc.
    from db.session import AdminSessionFactory
    from services.audit import record as audit_record

    async with AdminSessionFactory() as session:
        await audit_record(
            session,
            organization_id=auth.organization_id,
            auth=auth,
            action="admin.cron.run_now",
            resource_type="cron",
            resource_id=None,
            before={},
            after={"cron_name": cron_name, "job_id": job.job_id},
        )
        await session.commit()

    return ok({"cron_name": cron_name, "job_id": job.job_id, "status": "enqueued"})


# ---------- Per-cron dedup state endpoints (cycle S1) ----------

_DEDUP_VALID_KINDS: frozenset[str] = frozenset({"cron_failure", "cron_stuck"})


@router.get("/crons/{name}/dedup-state")
async def get_cron_dedup_state(
    name: str,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Return outstanding dedup rows for a cron (one per alert kind)."""
    from services import cron_alert_dedup as svc

    rows = await svc.get_dedup_state(cron_name=name)
    return ok(rows)


@router.post("/crons/{name}/dedup-state/clear")
async def clear_cron_dedup_state(
    name: str,
    kind: str,
    auth: Annotated[AuthContext, Depends(require_role("admin"))],
) -> dict[str, Any]:
    """Clear a cron alert dedup row and write an audit row."""
    if kind not in _DEDUP_VALID_KINDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown kind {kind!r}; must be one of {sorted(_DEDUP_VALID_KINDS)}",
        )
    from db.session import AdminSessionFactory
    from services import audit as audit_mod
    from services import cron_alert_dedup as svc

    cleared = await svc.clear_alert(cron_name=name, kind=kind)

    async with AdminSessionFactory() as session:
        await audit_mod.record(
            session,
            organization_id=auth.organization_id,
            auth=auth,
            action="admin.cron.dedup_clear",
            resource_type="cron",
            resource_id=None,
            before={},
            after={"cron_name": name, "kind": kind},
        )
        await session.commit()

    return ok({"cleared": cleared, "cron_name": name, "kind": kind})
