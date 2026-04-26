"""SchedulePilot FastAPI router — Gantt/CPM scheduling + AI risk forecasting."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.schedulepilot import (
    Activity,
    ActivityCreate,
    ActivityUpdate,
    BaselineRequest,
    Dependency,
    DependencyCreate,
    RiskAssessment,
    RiskAssessmentCreate,
    ScheduleCreate,
    ScheduleDetail,
    ScheduleStatus,
    ScheduleSummary,
    ScheduleUpdate,
)

router = APIRouter(prefix="/api/v1/schedule", tags=["schedulepilot"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    """RowMapping → plain dict for Pydantic."""
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


# ---------- Schedules ----------


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO schedules
                  (organization_id, project_id, name, notes, data_date, created_by)
                VALUES
                  (:org, :project_id, :name, :notes, :data_date, :created_by)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "project_id": str(payload.project_id),
                    "name": payload.name,
                    "notes": payload.notes,
                    "data_date": payload.data_date,
                    "created_by": str(auth.user_id),
                },
            )
        ).one()
        await session.commit()
        return ok(_serialise_schedule(_row_to_dict(row)))


@router.get("/schedules")
async def list_schedules(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    status_filter: ScheduleStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    where = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(auth.organization_id)}
    if project_id is not None:
        where.append("project_id = :project_id")
        params["project_id"] = str(project_id)
    if status_filter is not None:
        where.append("status = :status")
        params["status"] = status_filter.value

    where_sql = " AND ".join(where)

    async with TenantAwareSession(auth.organization_id) as session:
        total = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM schedules WHERE {where_sql}"),
                params,
            )
        ).scalar_one()
        rows = (
            await session.execute(
                text(
                    f"""
                SELECT s.*,
                  (SELECT COUNT(*) FROM schedule_activities a
                     WHERE a.schedule_id = s.id) AS activity_count,
                  (SELECT COUNT(*) FROM schedule_activities a
                     WHERE a.schedule_id = s.id
                       AND a.baseline_finish IS NOT NULL
                       AND a.planned_finish IS NOT NULL
                       AND a.planned_finish > a.baseline_finish) AS behind_schedule_count,
                  COALESCE((SELECT AVG(percent_complete)
                              FROM schedule_activities a
                              WHERE a.schedule_id = s.id), 0) AS avg_pct
                FROM schedules s
                WHERE {where_sql}
                ORDER BY s.created_at DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).all()

        items = []
        for r in rows:
            d = _row_to_dict(r)
            base = _serialise_schedule(d)
            base["activity_count"] = int(d.get("activity_count") or 0)
            base["behind_schedule_count"] = int(d.get("behind_schedule_count") or 0)
            base["percent_complete"] = float(d.get("avg_pct") or 0)
            # on_critical_path_count requires the latest risk assessment — see GET detail
            base["on_critical_path_count"] = 0
            items.append(base)

    return paginated(items, page=offset // limit + 1, per_page=limit, total=int(total or 0))


@router.get("/schedules/{schedule_id}")
async def get_schedule(
    schedule_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        sched = (
            await session.execute(
                text("SELECT * FROM schedules WHERE id = :id"),
                {"id": str(schedule_id)},
            )
        ).one_or_none()
        if sched is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

        activities = (
            await session.execute(
                text(
                    """
                SELECT * FROM schedule_activities
                WHERE schedule_id = :id
                ORDER BY sort_order, code
                """
                ),
                {"id": str(schedule_id)},
            )
        ).all()
        deps = (
            await session.execute(
                text(
                    """
                SELECT d.*
                FROM schedule_dependencies d
                JOIN schedule_activities a ON a.id = d.predecessor_id
                WHERE a.schedule_id = :id
                """
                ),
                {"id": str(schedule_id)},
            )
        ).all()
        latest_risk = (
            await session.execute(
                text(
                    """
                SELECT * FROM schedule_risk_assessments
                WHERE schedule_id = :id
                ORDER BY generated_at DESC
                LIMIT 1
                """
                ),
                {"id": str(schedule_id)},
            )
        ).one_or_none()

    sched_d = _row_to_dict(sched)
    base = _serialise_schedule(sched_d)
    base["activity_count"] = len(activities)
    base["behind_schedule_count"] = sum(
        1
        for a in activities
        if (
            (ad := _row_to_dict(a)).get("baseline_finish")
            and ad.get("planned_finish")
            and ad["planned_finish"] > ad["baseline_finish"]
        )
    )
    base["percent_complete"] = (
        float(sum(float(_row_to_dict(a).get("percent_complete") or 0) for a in activities)) / len(activities)
        if activities
        else 0.0
    )
    cpm_codes: list[str] = list(_row_to_dict(latest_risk).get("critical_path_codes") or []) if latest_risk else []
    base["on_critical_path_count"] = sum(1 for a in activities if _row_to_dict(a).get("code") in set(cpm_codes))

    detail = ScheduleDetail(
        schedule=ScheduleSummary.model_validate(base),
        activities=[Activity.model_validate(_row_to_dict(a)) for a in activities],
        dependencies=[Dependency.model_validate(_row_to_dict(d)) for d in deps],
        latest_risk_assessment=(RiskAssessment.model_validate(_row_to_dict(latest_risk)) if latest_risk else None),
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: UUID,
    payload: ScheduleUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    if "status" in fields:
        fields["status"] = fields["status"].value if hasattr(fields["status"], "value") else fields["status"]

    set_sql = ", ".join(f"{k} = :{k}" for k in fields)
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    f"""
                UPDATE schedules SET {set_sql}, updated_at = NOW()
                WHERE id = :id
                RETURNING *
                """
                ),
                {**fields, "id": str(schedule_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
        await session.commit()
        return ok(_serialise_schedule(_row_to_dict(row)))


@router.post("/schedules/{schedule_id}/baseline")
async def baseline_schedule(
    schedule_id: UUID,
    payload: BaselineRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Snapshot planned_* into baseline_*, mark schedule as `baselined`.

    Idempotent only by intent — calling twice will overwrite the previous
    baseline. Auditors who need history can rely on the assessment trail.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        sched = (
            await session.execute(
                text("SELECT id FROM schedules WHERE id = :id"),
                {"id": str(schedule_id)},
            )
        ).one_or_none()
        if sched is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

        await session.execute(
            text(
                """
            UPDATE schedule_activities
            SET baseline_start  = planned_start,
                baseline_finish = planned_finish,
                updated_at      = NOW()
            WHERE schedule_id = :id
            """
            ),
            {"id": str(schedule_id)},
        )
        new_notes_sql = ", notes = COALESCE(notes, '') || E'\\n' || :note" if payload.note else ""
        params: dict[str, Any] = {"id": str(schedule_id)}
        if payload.note:
            params["note"] = payload.note
        row = (
            await session.execute(
                text(
                    f"""
                UPDATE schedules SET
                  status          = 'baselined',
                  baseline_set_at = NOW(),
                  updated_at      = NOW()
                  {new_notes_sql}
                WHERE id = :id
                RETURNING *
                """
                ),
                params,
            )
        ).one()
        await session.commit()
        return ok(_serialise_schedule(_row_to_dict(row)))


# ---------- Activities ----------


@router.post("/schedules/{schedule_id}/activities", status_code=status.HTTP_201_CREATED)
async def create_activity(
    schedule_id: UUID,
    payload: ActivityCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        sched = (
            await session.execute(
                text("SELECT id FROM schedules WHERE id = :id"),
                {"id": str(schedule_id)},
            )
        ).one_or_none()
        if sched is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

        row = (
            await session.execute(
                text(
                    """
                INSERT INTO schedule_activities
                  (organization_id, schedule_id, code, name, activity_type,
                   planned_start, planned_finish, planned_duration_days,
                   assignee_id, notes, sort_order)
                VALUES
                  (:org, :schedule_id, :code, :name, :activity_type,
                   :ps, :pf, :pd, :assignee, :notes, :sort_order)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "schedule_id": str(schedule_id),
                    "code": payload.code,
                    "name": payload.name,
                    "activity_type": payload.activity_type.value,
                    "ps": payload.planned_start,
                    "pf": payload.planned_finish,
                    "pd": payload.planned_duration_days,
                    "assignee": (str(payload.assignee_id) if payload.assignee_id else None),
                    "notes": payload.notes,
                    "sort_order": payload.sort_order,
                },
            )
        ).one()
        await session.commit()
        return ok(Activity.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.patch("/activities/{activity_id}")
async def update_activity(
    activity_id: UUID,
    payload: ActivityUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    for k in ("activity_type", "status"):
        if k in fields and hasattr(fields[k], "value"):
            fields[k] = fields[k].value
    if "assignee_id" in fields and fields["assignee_id"] is not None:
        fields["assignee_id"] = str(fields["assignee_id"])

    set_sql = ", ".join(f"{k} = :{k}" for k in fields)
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    f"""
                UPDATE schedule_activities SET {set_sql}, updated_at = NOW()
                WHERE id = :id
                RETURNING *
                """
                ),
                {**fields, "id": str(activity_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found")
        await session.commit()
        return ok(Activity.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity(
    activity_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text("DELETE FROM schedule_activities WHERE id = :id"),
            {"id": str(activity_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found")
        await session.commit()


# ---------- Dependencies ----------


@router.post("/dependencies", status_code=status.HTTP_201_CREATED)
async def create_dependency(
    payload: DependencyCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    if payload.predecessor_id == payload.successor_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Predecessor and successor must differ")

    async with TenantAwareSession(auth.organization_id) as session:
        # Cycle detection: walk from successor's outbound edges; if we reach
        # the predecessor, the new edge would close a cycle.
        if await _would_create_cycle(session, payload.predecessor_id, payload.successor_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Dependency would introduce a cycle",
            )
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO schedule_dependencies
                  (organization_id, predecessor_id, successor_id,
                   relationship_type, lag_days)
                VALUES
                  (:org, :pred, :succ, :rel, :lag)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "pred": str(payload.predecessor_id),
                    "succ": str(payload.successor_id),
                    "rel": payload.relationship_type.value,
                    "lag": payload.lag_days,
                },
            )
        ).one()
        await session.commit()
        return ok(Dependency.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.delete("/dependencies/{dep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dependency(
    dep_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text("DELETE FROM schedule_dependencies WHERE id = :id"),
            {"id": str(dep_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Dependency not found")
        await session.commit()


# ---------- Risk assessment ----------


@router.post("/schedules/{schedule_id}/risk-assessment", status_code=status.HTTP_201_CREATED)
async def run_risk_assessment(
    schedule_id: UUID,
    payload: RiskAssessmentCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Compute CPM critical path + delegate top-N risk narration to the LLM.

    Inline-pipeline pattern (matches HANDOVER): the heavy lifting lives in
    `ml.pipelines.schedulepilot.run_risk_assessment`. The router fetches the
    inputs, invokes the pipeline, and persists the output row.
    """
    from ml.pipelines.schedulepilot import run_risk_assessment as run_pipeline

    async with TenantAwareSession(auth.organization_id) as session:
        sched = (
            await session.execute(
                text("SELECT * FROM schedules WHERE id = :id"),
                {"id": str(schedule_id)},
            )
        ).one_or_none()
        if sched is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

        activities = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text("SELECT * FROM schedule_activities WHERE schedule_id = :id"),
                    {"id": str(schedule_id)},
                )
            ).all()
        ]
        deps = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text(
                        """
                    SELECT d.* FROM schedule_dependencies d
                    JOIN schedule_activities a ON a.id = d.predecessor_id
                    WHERE a.schedule_id = :id
                    """
                    ),
                    {"id": str(schedule_id)},
                )
            ).all()
        ]

        sched_d = _row_to_dict(sched)
        result = await run_pipeline(activities, deps, force=payload.force)

        row = (
            await session.execute(
                text(
                    """
                INSERT INTO schedule_risk_assessments
                  (organization_id, schedule_id, model_version, data_date_used,
                   overall_slip_days, confidence_pct, critical_path_codes,
                   top_risks, input_summary, notes)
                VALUES
                  (:org, :sid, :mv, :dd, :slip, :conf,
                   :cpm, CAST(:risks AS jsonb), CAST(:summary AS jsonb), :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "sid": str(schedule_id),
                    "mv": result.get("model_version"),
                    "dd": sched_d.get("data_date"),
                    "slip": result["overall_slip_days"],
                    "conf": result.get("confidence_pct"),
                    "cpm": result["critical_path_codes"],
                    "risks": json.dumps(result["top_risks"]),
                    "summary": json.dumps(result["input_summary"]),
                    "notes": result.get("notes"),
                },
            )
        ).one()
        await session.commit()
        return ok(RiskAssessment.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.get("/schedules/{schedule_id}/risk-assessments")
async def list_risk_assessments(
    schedule_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    limit: int = Query(default=10, ge=1, le=50),
):
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                SELECT * FROM schedule_risk_assessments
                WHERE schedule_id = :id
                ORDER BY generated_at DESC
                LIMIT :limit
                """
                ),
                {"id": str(schedule_id), "limit": limit},
            )
        ).all()
    items = [RiskAssessment.model_validate(_row_to_dict(r)).model_dump(mode="json") for r in rows]
    return ok(items)


# ---------- Helpers ----------


def _serialise_schedule(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "organization_id": d["organization_id"],
        "project_id": d["project_id"],
        "name": d["name"],
        "status": d["status"],
        "baseline_set_at": d.get("baseline_set_at"),
        "data_date": d.get("data_date"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "activity_count": int(d.get("activity_count") or 0),
        "behind_schedule_count": int(d.get("behind_schedule_count") or 0),
        "on_critical_path_count": int(d.get("on_critical_path_count") or 0),
        "percent_complete": float(d.get("percent_complete") or 0),
    }


async def _would_create_cycle(session: Any, predecessor_id: UUID, successor_id: UUID) -> bool:
    """Detect cycles via a recursive CTE rooted at the proposed successor."""
    result = (
        await session.execute(
            text(
                """
            WITH RECURSIVE descendants(id) AS (
                SELECT successor_id AS id
                  FROM schedule_dependencies
                 WHERE predecessor_id = :start
                UNION
                SELECT d.successor_id
                  FROM schedule_dependencies d
                  JOIN descendants ON d.predecessor_id = descendants.id
            )
            SELECT 1 FROM descendants WHERE id = :target LIMIT 1
            """
            ),
            {"start": str(successor_id), "target": str(predecessor_id)},
        )
    ).first()
    return result is not None
