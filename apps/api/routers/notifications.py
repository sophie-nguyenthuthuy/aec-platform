"""User-facing notification settings: project watch CRUD.

Watches drive the `daily_activity_digest_cron` (workers/queue.py). The
activity-feed *page* remains org-wide regardless of watches; this is
strictly the push-channel opt-in.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.core import Project, ProjectWatch
from schemas.notifications import (
    ProjectWatch as ProjectWatchOut,
)
from schemas.notifications import (
    ProjectWatchCreate,
    WatchedProject,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


# ---------- List my watches ----------


@router.get("/watches")
async def list_my_watches(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return every project the calling user has subscribed to. Joined to
    `projects` so the UI shows the project name without a second fetch."""
    rows = (
        await db.execute(
            select(
                ProjectWatch.id,
                ProjectWatch.project_id,
                ProjectWatch.created_at,
                Project.name.label("project_name"),
            )
            .join(Project, Project.id == ProjectWatch.project_id)
            .where(
                ProjectWatch.user_id == auth.user_id,
                ProjectWatch.organization_id == auth.organization_id,
            )
            .order_by(ProjectWatch.created_at.desc())
        )
    ).all()

    items = [
        WatchedProject(
            watch_id=r.id,
            project_id=r.project_id,
            project_name=r.project_name,
            created_at=r.created_at,
        ).model_dump(mode="json")
        for r in rows
    ]
    return ok(items)


# ---------- Add a watch ----------


@router.post("/watches", status_code=status.HTTP_201_CREATED)
async def create_watch(
    payload: ProjectWatchCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Subscribe the caller to a project's daily digest.

    Idempotent: re-watching an already-watched project returns the
    existing row instead of duplicating. Validates that the project
    belongs to caller's org (RLS would also block a cross-tenant insert,
    but we want a clean 404 instead of an opaque RLS error).
    """
    project = (
        await db.execute(
            select(Project).where(
                Project.id == payload.project_id,
                Project.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    existing = (
        await db.execute(
            select(ProjectWatch).where(
                ProjectWatch.user_id == auth.user_id,
                ProjectWatch.project_id == payload.project_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ok(ProjectWatchOut.model_validate(existing).model_dump(mode="json"))

    watch = ProjectWatch(
        id=uuid4(),
        organization_id=auth.organization_id,
        user_id=auth.user_id,
        project_id=payload.project_id,
    )
    db.add(watch)
    try:
        await db.commit()
    except IntegrityError:
        # Race: another concurrent request inserted between our SELECT
        # and INSERT. Reload the row that won and return it.
        await db.rollback()
        existing = (
            await db.execute(
                select(ProjectWatch).where(
                    and_(
                        ProjectWatch.user_id == auth.user_id,
                        ProjectWatch.project_id == payload.project_id,
                    )
                )
            )
        ).scalar_one()
        return ok(ProjectWatchOut.model_validate(existing).model_dump(mode="json"))

    await db.refresh(watch)
    return ok(ProjectWatchOut.model_validate(watch).model_dump(mode="json"))


# ---------- Delete a watch ----------


@router.delete("/watches/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Unsubscribe. Idempotent — deleting a non-existent watch is a 204
    (the desired end state is "you're not watching it" either way)."""
    watch = (
        await db.execute(
            select(ProjectWatch).where(
                ProjectWatch.user_id == auth.user_id,
                ProjectWatch.project_id == project_id,
                ProjectWatch.organization_id == auth.organization_id,
            )
        )
    ).scalar_one_or_none()
    if watch is None:
        return None
    await db.delete(watch)
    await db.commit()
    return None
