"""Cross-module 'today' inbox — `GET /api/v1/me/inbox`.

A single fan-out aggregator that pulls per-user pending items across
RFIs, punch items, defects, submittals, change orders, and CO candidates,
then returns them in two buckets:

  * `assigned_to_me` — explicit assignment via a user FK column.
  * `awaiting_review` — org-level pending items where assignment is
    implicit in the role.

Each query is small + indexed; the aggregator caps results per source so
a tenant with thousands of open RFIs can't blow up the endpoint. The UI
treats this as a triage view: clicking an item deep-links to the full
record on the source module's page.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.inbox import (
    InboxBucket,
    InboxBucketSummary,
    InboxItem,
    InboxItemKind,
    InboxResponse,
)

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/inbox")
async def my_inbox(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    limit_per_source: int = Query(default=20, ge=1, le=50),
):
    """Aggregate pending items across modules for the calling user.

    `project_id` is optional — when set, every source filters to that
    project. The default unscoped view is the supe's "what's on my plate
    today" home page.
    """
    user_id = auth.user_id

    async with TenantAwareSession(auth.organization_id) as session:
        # Six small queries, fanned out in parallel. Each is <2ms typically;
        # gathering them keeps the endpoint under a 50ms budget even on a
        # tenant with thousands of open items per source.
        rfis, punch_items, defects, submittals, cos, candidates = await asyncio.gather(
            _rfis_assigned(session, user_id, project_id, limit_per_source),
            _punch_items_assigned(session, user_id, project_id, limit_per_source),
            _defects_assigned(session, user_id, project_id, limit_per_source),
            _submittals_for_review(session, project_id, limit_per_source),
            _change_orders_for_review(session, project_id, limit_per_source),
            _co_candidates_pending(session, project_id, limit_per_source),
        )

    items: list[InboxItem] = [*rfis, *punch_items, *defects, *submittals, *cos, *candidates]

    bucket_counts: dict[InboxBucket, int] = {}
    for it in items:
        bucket_counts[it.bucket] = bucket_counts.get(it.bucket, 0) + 1
    summary = [InboxBucketSummary(bucket=b, count=c) for b, c in bucket_counts.items()]

    return ok(InboxResponse(items=items, summary=summary, total=len(items)).model_dump(mode="json"))


# ---------- assigned_to_me sources ----------


async def _rfis_assigned(session: Any, user_id: UUID, project_id: UUID | None, limit: int) -> list[InboxItem]:
    where = "r.assigned_to = :uid AND r.status IN ('open', 'answered')"
    params: dict[str, Any] = {"uid": str(user_id), "limit": limit}
    if project_id is not None:
        where += " AND r.project_id = :pid"
        params["pid"] = str(project_id)
    rows = (
        await session.execute(
            text(
                f"""
            SELECT r.id, r.project_id, p.name AS project_name, r.subject,
                   r.number, r.status, r.priority, r.due_date, r.created_at
            FROM rfis r
            LEFT JOIN projects p ON p.id = r.project_id
            WHERE {where}
            ORDER BY r.due_date NULLS LAST, r.created_at DESC
            LIMIT :limit
            """
            ),
            params,
        )
    ).all()
    return [
        InboxItem(
            kind=InboxItemKind.rfi,
            bucket=InboxBucket.assigned_to_me,
            id=r._mapping["id"],
            project_id=r._mapping.get("project_id"),
            project_name=r._mapping.get("project_name"),
            title=r._mapping["subject"],
            subtitle=r._mapping.get("number"),
            status=r._mapping.get("status"),
            severity=r._mapping.get("priority"),
            due_date=r._mapping.get("due_date"),
            created_at=r._mapping.get("created_at"),
            deep_link=f"/drawbridge/rfis/{r._mapping['id']}",
        )
        for r in rows
    ]


async def _punch_items_assigned(session: Any, user_id: UUID, project_id: UUID | None, limit: int) -> list[InboxItem]:
    where = "i.assigned_user_id = :uid AND i.status IN ('open', 'in_progress', 'fixed')"
    params: dict[str, Any] = {"uid": str(user_id), "limit": limit}
    if project_id is not None:
        where += " AND pl.project_id = :pid"
        params["pid"] = str(project_id)
    rows = (
        await session.execute(
            text(
                f"""
            SELECT i.id, i.list_id, pl.project_id, p.name AS project_name,
                   i.description, i.item_number, i.status, i.severity,
                   i.due_date, i.created_at
            FROM punch_items i
            JOIN punch_lists pl ON pl.id = i.list_id
            LEFT JOIN projects p ON p.id = pl.project_id
            WHERE {where}
            ORDER BY i.due_date NULLS LAST, i.created_at DESC
            LIMIT :limit
            """
            ),
            params,
        )
    ).all()
    return [
        InboxItem(
            kind=InboxItemKind.punch_item,
            bucket=InboxBucket.assigned_to_me,
            id=r._mapping["id"],
            project_id=r._mapping.get("project_id"),
            project_name=r._mapping.get("project_name"),
            title=r._mapping["description"],
            subtitle=f"#{r._mapping['item_number']}",
            status=r._mapping.get("status"),
            severity=r._mapping.get("severity"),
            due_date=r._mapping.get("due_date"),
            created_at=r._mapping.get("created_at"),
            deep_link=f"/punchlist/{r._mapping['list_id']}",
        )
        for r in rows
    ]


async def _defects_assigned(session: Any, user_id: UUID, project_id: UUID | None, limit: int) -> list[InboxItem]:
    where = "d.assignee_id = :uid AND d.status IN ('open', 'assigned', 'in_progress')"
    params: dict[str, Any] = {"uid": str(user_id), "limit": limit}
    if project_id is not None:
        where += " AND d.project_id = :pid"
        params["pid"] = str(project_id)
    rows = (
        await session.execute(
            text(
                f"""
            SELECT d.id, d.project_id, p.name AS project_name,
                   d.description, d.status, d.priority, d.due_date, d.created_at
            FROM defects d
            LEFT JOIN projects p ON p.id = d.project_id
            WHERE {where}
            ORDER BY d.due_date NULLS LAST, d.created_at DESC
            LIMIT :limit
            """
            ),
            params,
        )
    ).all()
    return [
        InboxItem(
            kind=InboxItemKind.defect,
            bucket=InboxBucket.assigned_to_me,
            id=r._mapping["id"],
            project_id=r._mapping.get("project_id"),
            project_name=r._mapping.get("project_name"),
            title=r._mapping["description"],
            subtitle=None,
            status=r._mapping.get("status"),
            severity=r._mapping.get("priority"),
            due_date=r._mapping.get("due_date"),
            created_at=r._mapping.get("created_at"),
            deep_link="/handover/defects",
        )
        for r in rows
    ]


# ---------- awaiting_review sources ----------


async def _submittals_for_review(session: Any, project_id: UUID | None, limit: int) -> list[InboxItem]:
    where = "ball_in_court = 'designer' AND status IN ('pending_review', 'under_review', 'revise_resubmit')"
    params: dict[str, Any] = {"limit": limit}
    if project_id is not None:
        where += " AND project_id = :pid"
        params["pid"] = str(project_id)
    rows = (
        await session.execute(
            text(
                f"""
            SELECT s.id, s.project_id, p.name AS project_name,
                   s.title, s.package_number, s.status, s.due_date, s.created_at
            FROM submittals s
            LEFT JOIN projects p ON p.id = s.project_id
            WHERE {where}
            ORDER BY s.due_date NULLS LAST, s.created_at DESC
            LIMIT :limit
            """
            ),
            params,
        )
    ).all()
    return [
        InboxItem(
            kind=InboxItemKind.submittal,
            bucket=InboxBucket.awaiting_review,
            id=r._mapping["id"],
            project_id=r._mapping.get("project_id"),
            project_name=r._mapping.get("project_name"),
            title=r._mapping["title"],
            subtitle=r._mapping.get("package_number"),
            status=r._mapping.get("status"),
            due_date=r._mapping.get("due_date"),
            created_at=r._mapping.get("created_at"),
            deep_link=f"/submittals/{r._mapping['id']}",
        )
        for r in rows
    ]


async def _change_orders_for_review(session: Any, project_id: UUID | None, limit: int) -> list[InboxItem]:
    where = "status IN ('submitted', 'reviewed')"
    params: dict[str, Any] = {"limit": limit}
    if project_id is not None:
        where += " AND project_id = :pid"
        params["pid"] = str(project_id)
    rows = (
        await session.execute(
            text(
                f"""
            SELECT co.id, co.project_id, p.name AS project_name,
                   co.title, co.number, co.status, co.created_at
            FROM change_orders co
            LEFT JOIN projects p ON p.id = co.project_id
            WHERE {where}
            ORDER BY co.created_at DESC
            LIMIT :limit
            """
            ),
            params,
        )
    ).all()
    return [
        InboxItem(
            kind=InboxItemKind.change_order,
            bucket=InboxBucket.awaiting_review,
            id=r._mapping["id"],
            project_id=r._mapping.get("project_id"),
            project_name=r._mapping.get("project_name"),
            title=r._mapping["title"],
            subtitle=r._mapping.get("number"),
            status=r._mapping.get("status"),
            created_at=r._mapping.get("created_at"),
            deep_link=f"/changeorder/{r._mapping['id']}",
        )
        for r in rows
    ]


async def _co_candidates_pending(session: Any, project_id: UUID | None, limit: int) -> list[InboxItem]:
    where = "accepted_co_id IS NULL AND rejected_at IS NULL"
    params: dict[str, Any] = {"limit": limit}
    if project_id is not None:
        where += " AND project_id = :pid"
        params["pid"] = str(project_id)
    rows = (
        await session.execute(
            text(
                f"""
            SELECT c.id, c.project_id, p.name AS project_name,
                   (c.proposal->>'title') AS proposal_title,
                   c.source_kind, c.created_at
            FROM change_order_candidates c
            LEFT JOIN projects p ON p.id = c.project_id
            WHERE {where}
            ORDER BY c.created_at DESC
            LIMIT :limit
            """
            ),
            params,
        )
    ).all()
    return [
        InboxItem(
            kind=InboxItemKind.co_candidate,
            bucket=InboxBucket.awaiting_review,
            id=r._mapping["id"],
            project_id=r._mapping.get("project_id"),
            project_name=r._mapping.get("project_name"),
            title=r._mapping.get("proposal_title") or "(AI-suggested CO)",
            subtitle=r._mapping.get("source_kind"),
            status="pending",
            created_at=r._mapping.get("created_at"),
            deep_link="/changeorder",
        )
        for r in rows
    ]
