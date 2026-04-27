"""Cross-module project hub.

Surfaces a single "state of the project" view by rolling up per-module
counters from COSTPULSE, PULSE, DRAWBRIDGE, HANDOVER, SITEEYE, CODEGUARD,
and WINWORK into one response. The list endpoint returns only the cheap
counters that a card grid needs; the detail endpoint fans out to every
module for the selected project.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok, paginated
from db.deps import get_db
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from models.changeorder import ChangeOrderCandidate
from models.codeguard import ComplianceCheck, PermitChecklist
from models.core import Project
from models.costpulse import Estimate
from models.dailylog import DailyLog, DailyLogObservation
from models.drawbridge import Conflict, Document, Rfi
from models.handover import Defect, HandoverPackage, WarrantyItem
from models.pulse import ChangeOrder, Milestone, Task
from models.punchlist import PunchItem, PunchList
from models.schedulepilot import Activity as ScheduleActivity
from models.schedulepilot import (
    Schedule,
    ScheduleRiskAssessment,
)
from models.siteeye import SafetyIncident, SiteVisit
from models.submittals import Submittal
from models.winwork import Proposal
from schemas.projects import (
    ChangeorderStatus,
    CodeguardStatus,
    CostpulseStatus,
    DailylogStatus,
    DrawbridgeStatus,
    HandoverStatus,
    ProjectDetail,
    ProjectSummary,
    PulseStatus,
    PunchlistStatus,
    SchedulepilotStatus,
    SiteeyeStatus,
    SubmittalsStatus,
    WinworkStatus,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


# ---------- List (card grid) ----------


@router.get("")
async def list_projects(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(default=None, alias="status"),
    project_type: str | None = Query(default=None, alias="type"),
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """List projects for the caller's org with cheap per-card counters.

    The counters (`open_tasks`, `open_change_orders`, `document_count`) are
    enough to render a card grid — the detail endpoint provides the full
    per-module roll-up for a single project.
    """
    stmt = select(Project).where(Project.organization_id == auth.organization_id)
    if status_filter:
        stmt = stmt.where(Project.status == status_filter)
    if project_type:
        stmt = stmt.where(Project.type == project_type)
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{q}%"))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    projects = (
        (await db.execute(stmt.order_by(Project.created_at.desc()).limit(per_page).offset((page - 1) * per_page)))
        .scalars()
        .all()
    )

    if not projects:
        return paginated([], page=page, per_page=per_page, total=total)

    project_ids = [p.id for p in projects]

    # Three small aggregate queries beat N× per-project fan-out — each returns
    # one row per project_id that we merge into the summary projection.
    task_rows = (
        await db.execute(
            select(
                Task.project_id,
                func.count().filter(Task.status.in_(["todo", "in_progress"])).label("open_tasks"),
            )
            .where(Task.project_id.in_(project_ids))
            .group_by(Task.project_id)
        )
    ).all()
    co_rows = (
        await db.execute(
            select(
                ChangeOrder.project_id,
                func.count().label("open_cos"),
            )
            .where(
                ChangeOrder.project_id.in_(project_ids),
                ChangeOrder.status.in_(["draft", "submitted"]),
            )
            .group_by(ChangeOrder.project_id)
        )
    ).all()
    doc_rows = (
        await db.execute(
            select(
                Document.project_id,
                func.count().label("doc_count"),
            )
            .where(Document.project_id.in_(project_ids))
            .group_by(Document.project_id)
        )
    ).all()

    tasks_by_pid = {r.project_id: r.open_tasks for r in task_rows}
    cos_by_pid = {r.project_id: r.open_cos for r in co_rows}
    docs_by_pid = {r.project_id: r.doc_count for r in doc_rows}

    summaries = []
    for p in projects:
        summary = ProjectSummary.model_validate(p)
        summary.open_tasks = int(tasks_by_pid.get(p.id, 0))
        summary.open_change_orders = int(cos_by_pid.get(p.id, 0))
        summary.document_count = int(docs_by_pid.get(p.id, 0))
        summaries.append(summary.model_dump(mode="json"))

    return paginated(summaries, page=page, per_page=per_page, total=total)


# ---------- Detail (per-module roll-up) ----------


@router.get("/{project_id}")
async def get_project_detail(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    detail = ProjectDetail.model_validate(project)

    # Parallelize the 11 module roll-ups. Each helper gets its own
    # short-lived session because SQLAlchemy AsyncSession serialises
    # commands per-session — calling `await` on the same session from
    # multiple gathered tasks is undefined behaviour. A semaphore caps
    # in-flight tasks to 5 so a hub-detail render can't exhaust the
    # 10-connection pool under concurrent requests.
    #
    # Latency budget: was ~11×query_latency sequential; becomes
    # ~ceil(11/5)×query_latency = 3 round-trips of fan-out. For 2ms
    # queries that's 6ms instead of 22ms, but more importantly it
    # decouples slow sub-queries (e.g. SiteEye safety incident counts
    # at scale) from blocking the rest of the render.
    sem = asyncio.Semaphore(5)

    async def _run(helper, *args):
        async with sem, _scoped_session(auth.organization_id) as scoped:
            return await helper(scoped, *args)

    (
        winwork,
        costpulse,
        pulse_,
        drawbridge,
        handover,
        siteeye,
        codeguard,
        schedulepilot,
        submittals,
        dailylog,
        changeorder,
        punchlist,
    ) = await asyncio.gather(
        _run(_winwork_status, project_id),
        _run(_costpulse_status, project_id),
        _run(_pulse_status, project_id),
        _run(_drawbridge_status, project_id),
        _run(_handover_status, project_id),
        _run(_siteeye_status, project_id),
        _run(_codeguard_status, project_id),
        _run(_schedulepilot_status, project_id),
        _run(_submittals_status, project_id),
        _run(_dailylog_status, project_id),
        _run(_changeorder_status, project_id),
        _run(_punchlist_status, project_id),
    )
    detail.winwork = winwork
    detail.costpulse = costpulse
    detail.pulse = pulse_
    detail.drawbridge = drawbridge
    detail.handover = handover
    detail.siteeye = siteeye
    detail.codeguard = codeguard
    detail.schedulepilot = schedulepilot
    detail.submittals = submittals
    detail.dailylog = dailylog
    detail.changeorder = changeorder
    detail.punchlist = punchlist

    return ok(detail.model_dump(mode="json"))


# ---------- Helpers for the parallelised detail fan-out ----------


@asynccontextmanager
async def _scoped_session(organization_id: UUID):
    """Give each parallel helper its own tenant-scoped session.

    Lives here (not as a fixture / dependency) because it's tightly
    coupled to the fan-out shape — every callsite is one of the
    `_run(...)` invocations above.

    Why TenantAwareSession instead of a plain SessionFactory: the
    helpers' WHERE clauses already filter by `project_id`, but a few
    of them join through tables that don't carry `project_id` natively
    (e.g. some submittals/dailylog joins). RLS via `app.current_org_id`
    is the cheapest belt-and-suspenders here.
    """
    async with TenantAwareSession(organization_id) as session:
        yield session


# ---------- Per-module roll-up helpers ----------


async def _winwork_status(db: AsyncSession, project_id: UUID) -> WinworkStatus:
    """If this project was seeded from a won proposal, surface the link."""
    row = (
        await db.execute(
            select(Proposal).where(Proposal.project_id == project_id).order_by(Proposal.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return WinworkStatus()
    return WinworkStatus(
        proposal_id=row.id,
        proposal_status=row.status,
        total_fee_vnd=int(row.total_fee_vnd) if row.total_fee_vnd is not None else None,
    )


async def _costpulse_status(db: AsyncSession, project_id: UUID) -> CostpulseStatus:
    counts_row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(Estimate.status == "approved").label("approved"),
            ).where(Estimate.project_id == project_id)
        )
    ).one()

    latest = (
        await db.execute(
            select(Estimate.id, Estimate.total_vnd)
            .where(Estimate.project_id == project_id)
            .order_by(Estimate.created_at.desc())
            .limit(1)
        )
    ).one_or_none()

    return CostpulseStatus(
        estimate_count=int(counts_row.total or 0),
        approved_count=int(counts_row.approved or 0),
        latest_estimate_id=latest.id if latest else None,
        latest_total_vnd=int(latest.total_vnd) if latest and latest.total_vnd else None,
    )


async def _pulse_status(db: AsyncSession, project_id: UUID) -> PulseStatus:
    task_row = (
        await db.execute(
            select(
                func.count().filter(Task.status == "todo").label("todo"),
                func.count().filter(Task.status == "in_progress").label("in_progress"),
                func.count().filter(Task.status == "done").label("done"),
            ).where(Task.project_id == project_id)
        )
    ).one()

    open_cos = (
        await db.execute(
            select(func.count()).where(
                ChangeOrder.project_id == project_id,
                ChangeOrder.status.in_(["draft", "submitted"]),
            )
        )
    ).scalar_one()

    horizon = date.today() + timedelta(days=30)
    upcoming = (
        await db.execute(
            select(func.count()).where(
                Milestone.project_id == project_id,
                Milestone.status == "upcoming",
                Milestone.due_date <= horizon,
            )
        )
    ).scalar_one()

    return PulseStatus(
        tasks_todo=int(task_row.todo or 0),
        tasks_in_progress=int(task_row.in_progress or 0),
        tasks_done=int(task_row.done or 0),
        open_change_orders=int(open_cos or 0),
        upcoming_milestones=int(upcoming or 0),
    )


async def _drawbridge_status(db: AsyncSession, project_id: UUID) -> DrawbridgeStatus:
    docs = (await db.execute(select(func.count()).where(Document.project_id == project_id))).scalar_one()
    open_rfis = (
        await db.execute(
            select(func.count()).where(
                Rfi.project_id == project_id,
                Rfi.status.in_(["open", "answered"]),
            )
        )
    ).scalar_one()
    unresolved_conflicts = (
        await db.execute(
            select(func.count()).where(
                Conflict.project_id == project_id,
                Conflict.status != "resolved",
            )
        )
    ).scalar_one()
    return DrawbridgeStatus(
        document_count=int(docs or 0),
        open_rfi_count=int(open_rfis or 0),
        unresolved_conflict_count=int(unresolved_conflicts or 0),
    )


async def _handover_status(db: AsyncSession, project_id: UUID) -> HandoverStatus:
    packages = (await db.execute(select(func.count()).where(HandoverPackage.project_id == project_id))).scalar_one()
    open_defects = (
        await db.execute(
            select(func.count()).where(
                Defect.project_id == project_id,
                Defect.status.in_(["open", "assigned", "in_progress"]),
            )
        )
    ).scalar_one()
    warranty_row = (
        await db.execute(
            select(
                func.count().filter(WarrantyItem.status == "active").label("active"),
                func.count().filter(WarrantyItem.status == "expiring").label("expiring"),
            ).where(WarrantyItem.project_id == project_id)
        )
    ).one()
    return HandoverStatus(
        package_count=int(packages or 0),
        open_defect_count=int(open_defects or 0),
        warranty_active_count=int(warranty_row.active or 0),
        warranty_expiring_count=int(warranty_row.expiring or 0),
    )


async def _siteeye_status(db: AsyncSession, project_id: UUID) -> SiteeyeStatus:
    visits = (await db.execute(select(func.count()).where(SiteVisit.project_id == project_id))).scalar_one()
    open_incidents = (
        await db.execute(
            select(func.count()).where(
                SafetyIncident.project_id == project_id,
                SafetyIncident.status != "closed",
            )
        )
    ).scalar_one()
    return SiteeyeStatus(
        visit_count=int(visits or 0),
        open_safety_incident_count=int(open_incidents or 0),
    )


async def _codeguard_status(db: AsyncSession, project_id: UUID) -> CodeguardStatus:
    checks = (await db.execute(select(func.count()).where(ComplianceCheck.project_id == project_id))).scalar_one()
    permits = (await db.execute(select(func.count()).where(PermitChecklist.project_id == project_id))).scalar_one()
    return CodeguardStatus(
        compliance_check_count=int(checks or 0),
        permit_checklist_count=int(permits or 0),
    )


async def _schedulepilot_status(db: AsyncSession, project_id: UUID) -> SchedulepilotStatus:
    """Roll up SchedulePilot counters for the project hub.

    `behind_schedule_count` and `percent_complete` come from the activity
    rows directly. `on_critical_path_count` and `overall_slip_days` come
    from the LATEST risk assessment per schedule (if any) — falling back to
    zero when no assessment has been generated yet.
    """
    sched_count = (await db.execute(select(func.count()).where(Schedule.project_id == project_id))).scalar_one()

    activity_row = (
        await db.execute(
            select(
                func.count().label("activity_count"),
                func.coalesce(func.avg(ScheduleActivity.percent_complete), 0).label("avg_pct"),
                func.count()
                .filter(
                    ScheduleActivity.baseline_finish.is_not(None),
                    ScheduleActivity.planned_finish > ScheduleActivity.baseline_finish,
                )
                .label("behind"),
            )
            .select_from(ScheduleActivity)
            .join(Schedule, Schedule.id == ScheduleActivity.schedule_id)
            .where(Schedule.project_id == project_id)
        )
    ).one()

    # Latest assessment per schedule — sum critical-path codes across them.
    cpm_row = (
        await db.execute(
            select(func.coalesce(func.max(ScheduleRiskAssessment.overall_slip_days), 0).label("slip"))
            .select_from(ScheduleRiskAssessment)
            .join(Schedule, Schedule.id == ScheduleRiskAssessment.schedule_id)
            .where(Schedule.project_id == project_id)
        )
    ).one()

    on_cpm = (
        await db.execute(
            select(func.count())
            .select_from(ScheduleActivity)
            .join(Schedule, Schedule.id == ScheduleActivity.schedule_id)
            .where(
                Schedule.project_id == project_id,
                ScheduleActivity.code.in_(
                    select(func.unnest(ScheduleRiskAssessment.critical_path_codes))
                    .select_from(ScheduleRiskAssessment)
                    .join(Schedule, Schedule.id == ScheduleRiskAssessment.schedule_id)
                    .where(Schedule.project_id == project_id)
                    .scalar_subquery()
                ),
            )
        )
    ).scalar_one()

    return SchedulepilotStatus(
        schedule_count=int(sched_count or 0),
        activity_count=int(activity_row.activity_count or 0),
        behind_schedule_count=int(activity_row.behind or 0),
        on_critical_path_count=int(on_cpm or 0),
        overall_slip_days=int(cpm_row.slip or 0),
        percent_complete=float(activity_row.avg_pct or 0),
    )


async def _submittals_status(db: AsyncSession, project_id: UUID) -> SubmittalsStatus:
    row = (
        await db.execute(
            select(
                func.count()
                .filter(Submittal.status.in_(["pending_review", "under_review", "revise_resubmit"]))
                .label("open"),
                func.count().filter(Submittal.status == "revise_resubmit").label("revise"),
                func.count().filter(Submittal.status == "approved").label("approved"),
                func.count().filter(Submittal.ball_in_court == "designer").label("designer"),
                func.count().filter(Submittal.ball_in_court == "contractor").label("contractor"),
            ).where(Submittal.project_id == project_id)
        )
    ).one()
    return SubmittalsStatus(
        open_count=int(row.open or 0),
        revise_resubmit_count=int(row.revise or 0),
        approved_count=int(row.approved or 0),
        designer_court_count=int(row.designer or 0),
        contractor_court_count=int(row.contractor or 0),
    )


async def _dailylog_status(db: AsyncSession, project_id: UUID) -> DailylogStatus:
    counts = (
        await db.execute(
            select(
                func.count().label("log_count"),
                func.max(DailyLog.log_date).label("last_log_date"),
            ).where(DailyLog.project_id == project_id)
        )
    ).one()

    obs_row = (
        await db.execute(
            select(
                func.count().filter(DailyLogObservation.status.in_(["open", "in_progress"])).label("open"),
                func.count().filter(DailyLogObservation.severity.in_(["high", "critical"])).label("high"),
            )
            .select_from(DailyLogObservation)
            .join(DailyLog, DailyLog.id == DailyLogObservation.log_id)
            .where(DailyLog.project_id == project_id)
        )
    ).one()

    return DailylogStatus(
        log_count=int(counts.log_count or 0),
        open_observation_count=int(obs_row.open or 0),
        high_severity_observation_count=int(obs_row.high or 0),
        last_log_date=counts.last_log_date,
    )


async def _changeorder_status(db: AsyncSession, project_id: UUID) -> ChangeorderStatus:
    co_row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(ChangeOrder.status.in_(["draft", "submitted", "reviewed"])).label("open"),
                func.count().filter(ChangeOrder.status == "approved").label("approved"),
                func.coalesce(func.sum(ChangeOrder.cost_impact_vnd), 0).label("cost"),
                func.coalesce(func.sum(ChangeOrder.schedule_impact_days), 0).label("days"),
            ).where(ChangeOrder.project_id == project_id)
        )
    ).one()

    pending_candidates = (
        await db.execute(
            select(func.count()).where(
                ChangeOrderCandidate.project_id == project_id,
                ChangeOrderCandidate.accepted_co_id.is_(None),
                ChangeOrderCandidate.rejected_at.is_(None),
            )
        )
    ).scalar_one()

    return ChangeorderStatus(
        total_count=int(co_row.total or 0),
        open_count=int(co_row.open or 0),
        approved_count=int(co_row.approved or 0),
        pending_candidates=int(pending_candidates or 0),
        total_cost_impact_vnd=int(co_row.cost or 0),
        total_schedule_impact_days=int(co_row.days or 0),
    )


async def _punchlist_status(db: AsyncSession, project_id: UUID) -> PunchlistStatus:
    """Punch list roll-up — counts of lists by status + per-item severity totals.

    `high_severity_open_items` is a key surface signal for owners since a
    single high-severity finding can block sign-off; we want it visible
    on the project hub without drilling into each list.
    """
    list_counts = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(PunchList.status.in_(["open", "in_review"])).label("open_lists"),
                func.count().filter(PunchList.status == "signed_off").label("signed_off"),
            ).where(PunchList.project_id == project_id)
        )
    ).one()

    item_counts = (
        await db.execute(
            select(
                func.count().label("total_items"),
                func.count().filter(PunchItem.status.in_(["open", "in_progress"])).label("open_items"),
                func.count().filter(PunchItem.status == "verified").label("verified"),
                func.count()
                .filter(
                    PunchItem.severity == "high",
                    PunchItem.status.in_(["open", "in_progress"]),
                )
                .label("high_open"),
            )
            .select_from(PunchItem)
            .join(PunchList, PunchList.id == PunchItem.list_id)
            .where(PunchList.project_id == project_id)
        )
    ).one()

    return PunchlistStatus(
        list_count=int(list_counts.total or 0),
        open_list_count=int(list_counts.open_lists or 0),
        signed_off_list_count=int(list_counts.signed_off or 0),
        total_items=int(item_counts.total_items or 0),
        open_items=int(item_counts.open_items or 0),
        verified_items=int(item_counts.verified or 0),
        high_severity_open_items=int(item_counts.high_open or 0),
    )
