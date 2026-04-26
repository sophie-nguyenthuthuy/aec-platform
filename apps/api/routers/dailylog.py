"""DailyLog FastAPI router — daily field reports + LLM observation extraction."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.dailylog import (
    DailyLogCreate,
    DailyLogDetail,
    DailyLogStatus,
    DailyLogSummary,
    DailyLogUpdate,
    EquipmentEntry,
    ExtractRequest,
    ManpowerEntry,
    Observation,
    ObservationCreate,
    ObservationUpdate,
    PatternsResponse,
)

router = APIRouter(prefix="/api/v1/dailylog", tags=["dailylog"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


# ---------- DailyLog CRUD ----------


@router.post("/logs", status_code=status.HTTP_201_CREATED)
async def create_log(
    payload: DailyLogCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Create a daily log + nested manpower/equipment in one transaction.

    If `auto_extract=True` and the narrative is non-empty, the inline
    pipeline runs synchronously and observations are persisted alongside.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        log = (
            await session.execute(
                text(
                    """
                INSERT INTO daily_logs
                  (organization_id, project_id, log_date, weather, supervisor_id,
                   narrative, work_completed, issues_observed, created_by)
                VALUES
                  (:org, :pid, :ld, CAST(:weather AS jsonb), :sup,
                   :narr, :work, :issues, :created_by)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "pid": str(payload.project_id),
                    "ld": payload.log_date,
                    "weather": json.dumps(payload.weather),
                    "sup": str(auth.user_id),
                    "narr": payload.narrative,
                    "work": payload.work_completed,
                    "issues": payload.issues_observed,
                    "created_by": str(auth.user_id),
                },
            )
        ).one()
        log_d = _row_to_dict(log)
        log_id = log_d["id"]

        await _replace_manpower(session, auth.organization_id, log_id, payload.manpower)
        await _replace_equipment(session, auth.organization_id, log_id, payload.equipment)

        observations: list[dict[str, Any]] = []
        if payload.auto_extract and (payload.narrative or payload.issues_observed):
            from ml.pipelines.dailylog import extract_observations

            extracted = await extract_observations(
                narrative=payload.narrative,
                work_completed=payload.work_completed,
                issues_observed=payload.issues_observed,
                weather=payload.weather,
                manpower=[m.model_dump() for m in payload.manpower],
                equipment=[e.model_dump() for e in payload.equipment],
            )
            for obs in extracted:
                row = (
                    await session.execute(
                        text(
                            """
                        INSERT INTO daily_log_observations
                          (organization_id, log_id, kind, severity, description, source)
                        VALUES (:org, :lid, :kind, :sev, :desc, :src)
                        RETURNING *
                        """
                        ),
                        {
                            "org": str(auth.organization_id),
                            "lid": str(log_id),
                            "kind": obs["kind"],
                            "sev": obs["severity"],
                            "desc": obs["description"],
                            "src": obs.get("source", "llm_extracted"),
                        },
                    )
                ).one()
                observations.append(_row_to_dict(row))
            if extracted:
                await session.execute(
                    text("UPDATE daily_logs SET extracted_at = NOW() WHERE id = :id"),
                    {"id": str(log_id)},
                )

        await session.commit()

    return ok(_serialise_summary(log_d, manpower=payload.manpower, observations=observations))


@router.get("/logs")
async def list_logs(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    status_filter: DailyLogStatus | None = Query(default=None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    where = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(auth.organization_id)}
    if project_id:
        where.append("project_id = :project_id")
        params["project_id"] = str(project_id)
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter.value
    if date_from:
        where.append("log_date >= :df")
        params["df"] = date_from
    if date_to:
        where.append("log_date <= :dt")
        params["dt"] = date_to
    where_sql = " AND ".join(where)

    async with TenantAwareSession(auth.organization_id) as session:
        total = (await session.execute(text(f"SELECT COUNT(*) FROM daily_logs WHERE {where_sql}"), params)).scalar_one()
        rows = (
            await session.execute(
                text(
                    f"""
                SELECT
                  l.*,
                  COALESCE((SELECT SUM(headcount)
                              FROM daily_log_manpower m WHERE m.log_id = l.id), 0) AS total_headcount,
                  (SELECT COUNT(*) FROM daily_log_observations o
                     WHERE o.log_id = l.id AND o.status IN ('open', 'in_progress')) AS open_observations,
                  (SELECT COUNT(*) FROM daily_log_observations o
                     WHERE o.log_id = l.id AND o.severity IN ('high', 'critical')) AS high_severity_observations
                FROM daily_logs l
                WHERE {where_sql}
                ORDER BY log_date DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).all()

    items = [DailyLogSummary.model_validate(_row_to_dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=int(total or 0))


@router.get("/logs/{log_id}")
async def get_log(
    log_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        log = (
            await session.execute(
                text(
                    """
                SELECT
                  l.*,
                  COALESCE((SELECT SUM(headcount)
                              FROM daily_log_manpower m WHERE m.log_id = l.id), 0) AS total_headcount,
                  (SELECT COUNT(*) FROM daily_log_observations o
                     WHERE o.log_id = l.id AND o.status IN ('open', 'in_progress')) AS open_observations,
                  (SELECT COUNT(*) FROM daily_log_observations o
                     WHERE o.log_id = l.id AND o.severity IN ('high', 'critical')) AS high_severity_observations
                FROM daily_logs l WHERE id = :id
                """
                ),
                {"id": str(log_id)},
            )
        ).one_or_none()
        if log is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Daily log not found")
        manpower = (
            await session.execute(
                text("SELECT * FROM daily_log_manpower WHERE log_id = :id"),
                {"id": str(log_id)},
            )
        ).all()
        equipment = (
            await session.execute(
                text("SELECT * FROM daily_log_equipment WHERE log_id = :id"),
                {"id": str(log_id)},
            )
        ).all()
        observations = (
            await session.execute(
                text(
                    """
                SELECT * FROM daily_log_observations
                WHERE log_id = :id
                ORDER BY created_at DESC
                """
                ),
                {"id": str(log_id)},
            )
        ).all()

    log_d = _row_to_dict(log)
    detail = DailyLogDetail(
        summary=DailyLogSummary.model_validate(log_d),
        weather=log_d.get("weather") or {},
        narrative=log_d.get("narrative"),
        work_completed=log_d.get("work_completed"),
        issues_observed=log_d.get("issues_observed"),
        manpower=[ManpowerEntry.model_validate(_row_to_dict(m)) for m in manpower],
        equipment=[EquipmentEntry.model_validate(_row_to_dict(e)) for e in equipment],
        observations=[Observation.model_validate(_row_to_dict(o)) for o in observations],
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/logs/{log_id}")
async def update_log(
    log_id: UUID,
    payload: DailyLogUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Update narrative/weather/status. Manpower/equipment lists, if
    provided, are full replacements (delete + reinsert)."""
    fields = payload.model_dump(exclude_none=True, exclude={"manpower", "equipment"})
    if "status" in fields and hasattr(fields["status"], "value"):
        fields["status"] = fields["status"].value
    if "weather" in fields:
        fields["weather"] = json.dumps(fields["weather"])

    async with TenantAwareSession(auth.organization_id) as session:
        if fields:
            set_sql = ", ".join((f"{k} = CAST(:{k} AS jsonb)" if k == "weather" else f"{k} = :{k}") for k in fields)
            extra = ""
            if fields.get("status") == "submitted":
                extra = ", submitted_at = COALESCE(submitted_at, NOW())"
            elif fields.get("status") == "approved":
                extra = ", approved_at = NOW(), approved_by = :approver"
                fields_for_query = {**fields, "approver": str(auth.user_id)}
            else:
                fields_for_query = fields
            if fields.get("status") != "approved":
                fields_for_query = fields
            row = (
                await session.execute(
                    text(f"UPDATE daily_logs SET {set_sql}, updated_at = NOW(){extra} WHERE id = :id RETURNING *"),
                    {**fields_for_query, "id": str(log_id)},
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Daily log not found")

        if payload.manpower is not None:
            await _replace_manpower(session, auth.organization_id, log_id, payload.manpower)
        if payload.equipment is not None:
            await _replace_equipment(session, auth.organization_id, log_id, payload.equipment)

        await session.commit()

    return ok({"id": str(log_id), "updated": True})


@router.post("/logs/{log_id}/extract", status_code=status.HTTP_201_CREATED)
async def trigger_extract(
    log_id: UUID,
    payload: ExtractRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """(Re-)run the LLM extraction over an existing log's narrative."""
    from ml.pipelines.dailylog import extract_observations

    async with TenantAwareSession(auth.organization_id) as session:
        log = (
            await session.execute(
                text(
                    """
                SELECT id, narrative, work_completed, issues_observed, weather,
                       extracted_at
                FROM daily_logs WHERE id = :id
                """
                ),
                {"id": str(log_id)},
            )
        ).one_or_none()
        if log is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Daily log not found")
        log_d = _row_to_dict(log)
        if log_d.get("extracted_at") and not payload.force:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Already extracted; pass force=true to re-run",
            )

        manpower = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text("SELECT * FROM daily_log_manpower WHERE log_id = :id"),
                    {"id": str(log_id)},
                )
            ).all()
        ]
        equipment = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text("SELECT * FROM daily_log_equipment WHERE log_id = :id"),
                    {"id": str(log_id)},
                )
            ).all()
        ]

        extracted = await extract_observations(
            narrative=log_d.get("narrative"),
            work_completed=log_d.get("work_completed"),
            issues_observed=log_d.get("issues_observed"),
            weather=log_d.get("weather") or {},
            manpower=manpower,
            equipment=equipment,
        )
        # Replace prior llm_extracted observations to keep the audit clean.
        if payload.force:
            await session.execute(
                text(
                    """
                DELETE FROM daily_log_observations
                WHERE log_id = :id AND source = 'llm_extracted'
                """
                ),
                {"id": str(log_id)},
            )
        rows = []
        for obs in extracted:
            row = (
                await session.execute(
                    text(
                        """
                    INSERT INTO daily_log_observations
                      (organization_id, log_id, kind, severity, description, source)
                    VALUES (:org, :lid, :kind, :sev, :desc, 'llm_extracted')
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "lid": str(log_id),
                        "kind": obs["kind"],
                        "sev": obs["severity"],
                        "desc": obs["description"],
                    },
                )
            ).one()
            rows.append(_row_to_dict(row))
        await session.execute(
            text("UPDATE daily_logs SET extracted_at = NOW() WHERE id = :id"),
            {"id": str(log_id)},
        )
        await session.commit()

    return ok(
        {
            "log_id": str(log_id),
            "observations": [Observation.model_validate(r).model_dump(mode="json") for r in rows],
        }
    )


# ---------- Observations ----------


@router.post("/logs/{log_id}/observations", status_code=status.HTTP_201_CREATED)
async def create_observation(
    log_id: UUID,
    payload: ObservationCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO daily_log_observations
                  (organization_id, log_id, kind, severity, description, source,
                   related_safety_incident_id, notes)
                VALUES
                  (:org, :lid, :kind, :sev, :desc, :src, :sid, :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "lid": str(log_id),
                    "kind": payload.kind.value,
                    "sev": payload.severity.value,
                    "desc": payload.description,
                    "src": payload.source.value,
                    "sid": (str(payload.related_safety_incident_id) if payload.related_safety_incident_id else None),
                    "notes": payload.notes,
                },
            )
        ).one()
        await session.commit()
    return ok(Observation.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.patch("/observations/{obs_id}")
async def update_observation(
    obs_id: UUID,
    payload: ObservationUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    for k in ("kind", "severity", "status"):
        if k in fields and hasattr(fields[k], "value"):
            fields[k] = fields[k].value
    extra = ""
    if fields.get("status") == "resolved":
        extra = ", resolved_at = COALESCE(resolved_at, NOW())"

    set_sql = ", ".join(f"{k} = :{k}" for k in fields)
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(f"UPDATE daily_log_observations SET {set_sql}{extra} WHERE id = :id RETURNING *"),
                {**fields, "id": str(obs_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Observation not found")
        await session.commit()
    return ok(Observation.model_validate(_row_to_dict(row)).model_dump(mode="json"))


# ---------- Patterns ----------


@router.get("/projects/{project_id}/patterns")
async def get_patterns(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    date_from: date,
    date_to: date,
):
    """Aggregate observations + headcount + weather over a date range."""
    from ml.pipelines.dailylog import aggregate_patterns

    async with TenantAwareSession(auth.organization_id) as session:
        logs = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text(
                        """
                    SELECT id, log_date, weather
                    FROM daily_logs
                    WHERE project_id = :pid AND log_date BETWEEN :df AND :dt
                    """
                    ),
                    {"pid": str(project_id), "df": date_from, "dt": date_to},
                )
            ).all()
        ]
        manpower = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text(
                        """
                    SELECT m.headcount
                    FROM daily_log_manpower m
                    JOIN daily_logs l ON l.id = m.log_id
                    WHERE l.project_id = :pid AND l.log_date BETWEEN :df AND :dt
                    """
                    ),
                    {"pid": str(project_id), "df": date_from, "dt": date_to},
                )
            ).all()
        ]
        observations = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text(
                        """
                    SELECT o.kind, o.severity, o.description
                    FROM daily_log_observations o
                    JOIN daily_logs l ON l.id = o.log_id
                    WHERE l.project_id = :pid AND l.log_date BETWEEN :df AND :dt
                    """
                    ),
                    {"pid": str(project_id), "df": date_from, "dt": date_to},
                )
            ).all()
        ]

    out = aggregate_patterns(
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        log_rows=logs,
        manpower_rows=manpower,
        observation_rows=observations,
    )
    return ok(PatternsResponse.model_validate(out).model_dump(mode="json"))


# ---------- Helpers ----------


async def _replace_manpower(
    session: Any,
    org_id: UUID,
    log_id: UUID,
    rows: list[ManpowerEntry],
) -> None:
    await session.execute(
        text("DELETE FROM daily_log_manpower WHERE log_id = :id"),
        {"id": str(log_id)},
    )
    for m in rows:
        await session.execute(
            text(
                """
            INSERT INTO daily_log_manpower
              (organization_id, log_id, trade, headcount, hours_worked, foreman, notes)
            VALUES
              (:org, :lid, :trade, :hc, :hr, :fm, :notes)
            """
            ),
            {
                "org": str(org_id),
                "lid": str(log_id),
                "trade": m.trade,
                "hc": m.headcount,
                "hr": m.hours_worked,
                "fm": m.foreman,
                "notes": m.notes,
            },
        )


async def _replace_equipment(
    session: Any,
    org_id: UUID,
    log_id: UUID,
    rows: list[EquipmentEntry],
) -> None:
    await session.execute(
        text("DELETE FROM daily_log_equipment WHERE log_id = :id"),
        {"id": str(log_id)},
    )
    for e in rows:
        await session.execute(
            text(
                """
            INSERT INTO daily_log_equipment
              (organization_id, log_id, name, quantity, hours_used, state, notes)
            VALUES
              (:org, :lid, :name, :qty, :hr, :state, :notes)
            """
            ),
            {
                "org": str(org_id),
                "lid": str(log_id),
                "name": e.name,
                "qty": e.quantity,
                "hr": e.hours_used,
                "state": e.state.value if hasattr(e.state, "value") else e.state,
                "notes": e.notes,
            },
        )


def _serialise_summary(
    log_d: dict[str, Any],
    *,
    manpower: list[ManpowerEntry],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    summary_d = {
        "id": log_d["id"],
        "organization_id": log_d["organization_id"],
        "project_id": log_d["project_id"],
        "log_date": log_d["log_date"],
        "status": log_d["status"],
        "submitted_at": log_d.get("submitted_at"),
        "approved_at": log_d.get("approved_at"),
        "created_at": log_d["created_at"],
        "total_headcount": sum(m.headcount for m in manpower),
        "open_observations": sum(1 for o in observations if o.get("status", "open") == "open") if observations else 0,
        "high_severity_observations": sum(1 for o in observations if o.get("severity") in ("high", "critical"))
        if observations
        else 0,
    }
    return DailyLogSummary.model_validate(summary_d).model_dump(mode="json")
