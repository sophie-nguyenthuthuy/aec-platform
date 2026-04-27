"""Cross-module sync: SiteEye safety incidents → DailyLog observations.

When SiteEye detects a safety incident on a project, the natural place for
the field team to see it is in that day's daily log. This service implements
that hand-off:

  * Look up (or create a stub for) the DailyLog row for the project + the
    incident's `detected_at` date.
  * Insert a `daily_log_observations` row referencing the incident, with
    severity mapped from SiteEye's severity vocabulary.
  * Idempotent on (log_id, related_safety_incident_id) — running this twice
    for the same incident is a no-op.

Call sites
----------
  * The SiteEye safety inference worker (when a new incident is persisted).
  * `routers/siteeye.acknowledge_incident` — useful as a backfill so existing
    incidents that pre-date this sync still surface in the daily log on
    first ack.
  * Manual replay scripts.

Severity mapping
----------------
SiteEye's severity is free-form text today (typically `low`/`medium`/`high`/
`critical` but worker pipelines have been observed to write things like
`info` or `warning`). We coerce to DailyLog's enum (`low`/`medium`/`high`/
`critical`) with a defensive fallback to `medium`.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)


_SEVERITY_MAP: dict[str, str] = {
    "low": "low",
    "info": "low",
    "minor": "low",
    "medium": "medium",
    "warning": "medium",
    "moderate": "medium",
    "high": "high",
    "major": "high",
    "critical": "critical",
    "severe": "critical",
    "emergency": "critical",
}


def _normalise_severity(s: str | None) -> str:
    if not s:
        return "medium"
    return _SEVERITY_MAP.get(s.strip().lower(), "medium")


async def sync_incident_to_dailylog(
    session: Any,
    *,
    organization_id: UUID,
    incident: dict[str, Any] | Any,
) -> dict[str, Any] | None:
    """Materialise a daily-log observation for a safety incident.

    Parameters
    ----------
    session : sqlalchemy AsyncSession (or TenantAwareSession-yielded session)
        The caller is responsible for the surrounding transaction. We do
        NOT commit — that's the caller's call. We do issue an explicit
        SAVEPOINT? No. The simpler contract: caller commits or rolls back.
    incident : dict or row-like
        Must expose `id`, `project_id`, `detected_at`, `severity`,
        `incident_type`, `ai_description`. Pass either an ORM SafetyIncident
        instance or the equivalent dict (from a raw SQL row).

    Returns
    -------
    The inserted observation row as a dict, or `None` if the incident has
    no `project_id` (organisation-scoped incidents that don't tie to a
    project are skipped — the daily log is per-project).
    """
    inc = _coerce_incident(incident)

    if inc.get("project_id") is None:
        logger.debug(
            "dailylog_sync: skipping incident %s — no project_id",
            inc.get("id"),
        )
        return None

    project_id = inc["project_id"]
    log_date = _coerce_log_date(inc.get("detected_at"))

    # Find-or-create the daily log for this project + date.
    log_id = await _ensure_daily_log(session, organization_id=organization_id, project_id=project_id, log_date=log_date)

    # Idempotency check: an observation already exists for this incident on
    # any log of this org. SiteEye fires once per detection, but a worker
    # retry / backfill could call us repeatedly.
    existing = (
        await session.execute(
            text(
                """
                SELECT id FROM daily_log_observations
                WHERE related_safety_incident_id = :iid
                LIMIT 1
                """
            ),
            {"iid": str(inc["id"])},
        )
    ).one_or_none()
    if existing is not None:
        logger.debug(
            "dailylog_sync: incident %s already mirrored to observation %s",
            inc["id"],
            getattr(existing, "id", existing[0] if hasattr(existing, "__getitem__") else None),
        )
        return None

    description = _format_description(inc)
    severity = _normalise_severity(inc.get("severity"))

    row = (
        await session.execute(
            text(
                """
                INSERT INTO daily_log_observations
                  (organization_id, log_id, kind, severity, description,
                   source, related_safety_incident_id)
                VALUES
                  (:org, :lid, 'safety', :sev, :desc, 'siteeye_hit', :iid)
                RETURNING *
                """
            ),
            {
                "org": str(organization_id),
                "lid": str(log_id),
                "sev": severity,
                "desc": description,
                "iid": str(inc["id"]),
            },
        )
    ).one()
    return dict(row._mapping)


# ---------- Helpers ----------


def _coerce_incident(incident: Any) -> dict[str, Any]:
    """Accept ORM rows, sqlalchemy result rows, or plain dicts."""
    if isinstance(incident, dict):
        return incident
    if hasattr(incident, "_mapping"):
        return dict(incident._mapping)
    return {
        "id": getattr(incident, "id", None),
        "project_id": getattr(incident, "project_id", None),
        "detected_at": getattr(incident, "detected_at", None),
        "severity": getattr(incident, "severity", None),
        "incident_type": getattr(incident, "incident_type", None),
        "ai_description": getattr(incident, "ai_description", None),
    }


def _coerce_log_date(detected_at: Any) -> date:
    if isinstance(detected_at, date) and not isinstance(detected_at, datetime):
        return detected_at
    if isinstance(detected_at, datetime):
        return detected_at.date()
    return datetime.now(UTC).date()


def _format_description(inc: dict[str, Any]) -> str:
    """Compact summary that's useful even if the AI description is missing."""
    head = inc.get("incident_type") or "Cảnh báo SiteEye"
    desc = inc.get("ai_description") or ""
    if desc:
        # Trim long descriptions; the full incident is still linked via FK.
        desc = desc.strip()
        if len(desc) > 240:
            desc = desc[:237] + "..."
        return f"[SiteEye: {head}] {desc}"
    return f"[SiteEye: {head}]"


async def _ensure_daily_log(
    session: Any,
    *,
    organization_id: UUID,
    project_id: UUID,
    log_date: date,
) -> UUID:
    """Return the daily_logs.id for (project, date), creating a stub if needed.

    The unique constraint on (project_id, log_date) means an `INSERT ... ON
    CONFLICT DO NOTHING` keeps two concurrent workers from creating
    duplicates. The created stub has the default status='draft' so a
    supervisor can later open it and add narrative + manpower.
    """
    row = (
        await session.execute(
            text(
                """
                INSERT INTO daily_logs (organization_id, project_id, log_date)
                VALUES (:org, :pid, :ld)
                ON CONFLICT (project_id, log_date) DO UPDATE
                  SET log_date = EXCLUDED.log_date  -- no-op, but RETURNING * needs a row
                RETURNING id
                """
            ),
            {"org": str(organization_id), "pid": str(project_id), "ld": log_date},
        )
    ).one()
    return row.id if hasattr(row, "id") else row[0]
