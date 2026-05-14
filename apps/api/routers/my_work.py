"""Cross-module "Công việc đang thực hiện" — work-in-progress dashboard.

Aggregates two distinct work-tracking surfaces into one feed so a project
manager (or company director) can answer: "What's open right now, across
every project, that needs my attention?"

The two underlying tables:

  * `tasks` (Pulse kanban) — daily-work items. Status ∈ {todo, in_progress,
    review, blocked, done}. Carry `priority`, `assignee_id`, `due_date`.
  * `schedule_activities` (SchedulePilot WBS) — Gantt-style milestones and
    rolled-up phase buckets. Status ∈ {not_started, in_progress, complete,
    on_hold}. Carry `percent_complete`, `planned_finish`.

Filtering matrix (all optional):

  * `assignee` — defaults to "anyone". Set to "me" to scope to the
    caller's own queue (the "Công việc của tôi" tab in the UI).
  * `project_id` — narrow to a single project.
  * `status` — generic open/closed filter; UI exposes 3 buckets:
    `open` (default), `overdue`, `all`. Overdue is computed server-side
    against today.
  * `kind` — restrict to `task` or `activity` if a user wants one feed.

Pagination is `limit` + `offset` with a hard `limit ≤ 200` ceiling.
Cross-module ordering: open work first, then by due_date ASC, then by
recent updates DESC. Surfaces "deadline today" rows at the top without
losing recency for items without a due_date.

The endpoint is member-readable: every team member should be able to see
the team's queue (similar to the existing /api/v1/pulse/tasks endpoint).
RLS on both source tables keeps the result tenant-scoped automatically.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/api/v1/my-work", tags=["my-work"])


# Status buckets the UI surfaces — server resolves these to the right
# union of per-source statuses so the frontend doesn't have to.
StatusBucket = Literal["open", "overdue", "all"]
KindFilter = Literal["task", "activity"]
AssigneeScope = Literal["me", "anyone"]


@router.get("")
async def list_my_work(
    auth: Annotated[AuthContext, Depends(require_auth)],
    assignee: Annotated[AssigneeScope, Query()] = "anyone",
    status: Annotated[StatusBucket, Query()] = "open",
    kind: Annotated[KindFilter | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Aggregated list of open work items across Pulse + SchedulePilot.

    Each row carries enough context for the UI to deep-link back to the
    item's source view without a second round-trip.
    """
    today = date.today().isoformat()
    params: dict[str, object] = {
        "today": today,
        "limit": limit,
        "offset": offset,
    }

    # --- assignee filter ---
    assignee_clause_task = ""
    assignee_clause_act = ""
    if assignee == "me":
        assignee_clause_task = "AND t.assignee_id = :uid"
        assignee_clause_act = "AND a.assignee_id = :uid"
        params["uid"] = str(auth.user_id)

    # --- project filter ---
    project_clause_task = ""
    project_clause_act = ""
    if project_id is not None:
        project_clause_task = "AND t.project_id = :pid"
        project_clause_act = "AND s.project_id = :pid"
        params["pid"] = str(project_id)

    # --- status bucket ---
    # `open`: not-yet-done items.
    # `overdue`: open AND due_date < today (tasks) / planned_finish < today (activities).
    # `all`: everything visible to the user (no status filter).
    if status == "open":
        status_clause_task = "AND t.status NOT IN ('done', 'cancelled')"
        status_clause_act = "AND a.status NOT IN ('complete')"
    elif status == "overdue":
        status_clause_task = (
            "AND t.status NOT IN ('done', 'cancelled') "
            "AND t.due_date IS NOT NULL AND t.due_date < CAST(:today AS date)"
        )
        status_clause_act = (
            "AND a.status NOT IN ('complete') "
            "AND a.planned_finish IS NOT NULL AND a.planned_finish < CAST(:today AS date)"
        )
    else:  # all
        status_clause_task = ""
        status_clause_act = ""

    # --- kind filter ---
    # SQL union below; if `kind` set, we just omit the other half.
    include_tasks = kind != "activity"
    include_activities = kind != "task"

    parts: list[str] = []
    if include_tasks:
        parts.append(f"""
            SELECT
                'task'::text                        AS kind,
                t.id                                AS id,
                t.title                             AS title,
                t.status                            AS status,
                t.priority                          AS priority,
                t.project_id                        AS project_id,
                p.name                              AS project_name,
                t.assignee_id                       AS assignee_id,
                u.email                             AS assignee_email,
                t.due_date                          AS due_date,
                NULL::numeric                       AS percent_complete,
                t.created_at                        AS created_at
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            LEFT JOIN users u ON u.id = t.assignee_id
            WHERE 1=1
              {status_clause_task}
              {assignee_clause_task}
              {project_clause_task}
        """)
    if include_activities:
        parts.append(f"""
            SELECT
                'activity'::text                    AS kind,
                a.id                                AS id,
                a.name                              AS title,
                a.status                            AS status,
                NULL::text                          AS priority,
                s.project_id                        AS project_id,
                p.name                              AS project_name,
                a.assignee_id                       AS assignee_id,
                u.email                             AS assignee_email,
                a.planned_finish                    AS due_date,
                a.percent_complete                  AS percent_complete,
                a.created_at                        AS created_at
            FROM schedule_activities a
            JOIN schedules s ON s.id = a.schedule_id
            JOIN projects  p ON p.id = s.project_id
            LEFT JOIN users u ON u.id = a.assignee_id
            WHERE 1=1
              {status_clause_act}
              {assignee_clause_act}
              {project_clause_act}
        """)

    if not parts:
        # `kind` was set to neither task nor activity — shouldn't happen
        # because Literal guards it, but be defensive.
        return ok({"items": [], "total": 0, "limit": limit, "offset": offset})

    union_sql = " UNION ALL ".join(parts)

    # Outer query: order by due_date ASC NULLS LAST, then created_at DESC.
    # `NULLS LAST` keeps undated items below items with a deadline — the
    # "what's burning" feel we want for an overview dashboard.
    select_sql = f"""
        WITH combined AS ({union_sql})
        SELECT * FROM combined
        ORDER BY due_date ASC NULLS LAST, created_at DESC
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) FROM ({union_sql}) sub"

    async with TenantAwareSession(auth.organization_id) as session:
        rows = (await session.execute(text(select_sql), params)).mappings().all()
        total = (await session.execute(text(count_sql), params)).scalar_one()

    items = [
        {
            "kind": r["kind"],
            "id": str(r["id"]),
            "title": r["title"],
            "status": r["status"],
            "priority": r["priority"],
            "project_id": str(r["project_id"]),
            "project_name": r["project_name"],
            "assignee_id": str(r["assignee_id"]) if r["assignee_id"] else None,
            "assignee_email": r["assignee_email"],
            "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            "percent_complete": (
                float(r["percent_complete"]) if r["percent_complete"] is not None else None
            ),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]

    return ok(
        {
            "items": items,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
        }
    )


@router.get("/summary")
async def my_work_summary(
    auth: Annotated[AuthContext, Depends(require_auth)],
    assignee: Annotated[AssigneeScope, Query()] = "anyone",
):
    """KPI tiles for the dashboard header.

    Returns: total_open, overdue, due_today, completed_this_week. Cheap
    aggregates over the same union, separated from `list_my_work` so the
    UI can refetch them on a faster cadence than the row list.
    """
    today = date.today().isoformat()
    params: dict[str, object] = {"today": today}
    assignee_clause_t = ""
    assignee_clause_a = ""
    if assignee == "me":
        assignee_clause_t = "AND t.assignee_id = :uid"
        assignee_clause_a = "AND a.assignee_id = :uid"
        params["uid"] = str(auth.user_id)

    sql = f"""
        SELECT
            COUNT(*) FILTER (
                WHERE t.status NOT IN ('done', 'cancelled') {assignee_clause_t}
            ) AS open_tasks,
            COUNT(*) FILTER (
                WHERE t.status NOT IN ('done', 'cancelled')
                  AND t.due_date IS NOT NULL
                  AND t.due_date < CAST(:today AS date)
                  {assignee_clause_t}
            ) AS overdue_tasks,
            COUNT(*) FILTER (
                WHERE t.status NOT IN ('done', 'cancelled')
                  AND t.due_date = CAST(:today AS date)
                  {assignee_clause_t}
            ) AS due_today_tasks,
            COUNT(*) FILTER (
                WHERE t.status = 'done'
                  AND t.completed_at >= CAST(:today AS date) - INTERVAL '7 days'
                  {assignee_clause_t}
            ) AS completed_week_tasks
        FROM tasks t
    """

    sql_act = f"""
        SELECT
            COUNT(*) FILTER (
                WHERE a.status NOT IN ('complete') {assignee_clause_a}
            ) AS open_acts,
            COUNT(*) FILTER (
                WHERE a.status NOT IN ('complete')
                  AND a.planned_finish IS NOT NULL
                  AND a.planned_finish < CAST(:today AS date)
                  {assignee_clause_a}
            ) AS overdue_acts,
            COUNT(*) FILTER (
                WHERE a.status NOT IN ('complete')
                  AND a.planned_finish = CAST(:today AS date)
                  {assignee_clause_a}
            ) AS due_today_acts,
            COUNT(*) FILTER (
                WHERE a.status = 'complete'
                  AND a.actual_finish >= CAST(:today AS date) - INTERVAL '7 days'
                  {assignee_clause_a}
            ) AS completed_week_acts
        FROM schedule_activities a
    """

    async with TenantAwareSession(auth.organization_id) as session:
        task_row = (await session.execute(text(sql), params)).mappings().one()
        act_row = (await session.execute(text(sql_act), params)).mappings().one()

    return ok(
        {
            "open": int(task_row["open_tasks"]) + int(act_row["open_acts"]),
            "overdue": int(task_row["overdue_tasks"]) + int(act_row["overdue_acts"]),
            "due_today": int(task_row["due_today_tasks"]) + int(act_row["due_today_acts"]),
            "completed_week": (
                int(task_row["completed_week_tasks"]) + int(act_row["completed_week_acts"])
            ),
        }
    )
