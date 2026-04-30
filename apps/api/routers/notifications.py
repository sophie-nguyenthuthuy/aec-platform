"""User-facing notification settings: project watch CRUD.

Watches drive the `daily_activity_digest_cron` (workers/queue.py). The
activity-feed *page* remains org-wide regardless of watches; this is
strictly the push-channel opt-in.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.core import NotificationPreference, Project, ProjectWatch
from schemas.notifications import (
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
    ProjectWatchCreate,
    WatchedProject,
)
from schemas.notifications import (
    ProjectWatch as ProjectWatchOut,
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


# ---------- Per-user notification preferences ----------


# Stable, ops-curated list of alert kinds the UI exposes. Adding a new
# alert: bump this list + tell `services.ops_alerts.send_*` to read
# from the new key. The endpoint accepts arbitrary keys (so an
# experiment can ship an alert kind without UI churn) but the GET
# pre-fills these so a user sees every available switch even before
# their first opt-in.
_KNOWN_PREF_KEYS: tuple[str, ...] = (
    "scraper_drift",
    "rfq_deadline_summary",
    "weekly_digest_email",
)


@router.get("/preferences")
async def list_preferences(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the caller's preferences in the current org.

    Pre-fills every key in `_KNOWN_PREF_KEYS` with `email_enabled=False`,
    `slack_enabled=False` so the UI can render every switch even when
    the user hasn't touched them. Persisted rows override the defaults.
    """
    rows = (
        (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == auth.user_id,
                    NotificationPreference.organization_id == auth.organization_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {r.key: r for r in rows}
    out: list[dict] = []
    for key in _KNOWN_PREF_KEYS:
        existing = by_key.pop(key, None)
        if existing is not None:
            out.append(NotificationPreferenceOut.model_validate(existing).model_dump(mode="json"))
        else:
            out.append(
                {
                    # Synthetic id of all-zero so the UI can key on it
                    # for React lists; the real id arrives on first save.
                    "id": "00000000-0000-0000-0000-000000000000",
                    "key": key,
                    "email_enabled": False,
                    "slack_enabled": False,
                    "updated_at": None,
                }
            )
    # Surface any extra keys the user has rows for (experimental alerts
    # not in the curated list yet) — keeps the UI from silently losing
    # their preference if `_KNOWN_PREF_KEYS` shrinks.
    for extra in by_key.values():
        out.append(NotificationPreferenceOut.model_validate(extra).model_dump(mode="json"))
    return ok(out)


@router.put("/preferences/{key}")
async def upsert_preference(
    key: str,
    payload: NotificationPreferenceUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Idempotent upsert of one preference row.

    Both channel flags are optional in the body: omitting one leaves
    the existing value alone, so the UI can fire a single-checkbox
    update without round-tripping the other.
    """
    if not key or len(key) > 64:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid key")

    existing = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == auth.user_id,
                NotificationPreference.organization_id == auth.organization_id,
                NotificationPreference.key == key,
            )
        )
    ).scalar_one_or_none()

    # Snapshot the prior values BEFORE mutating so the audit row's
    # `before` is the actual previous state, not the post-update value.
    # For a brand-new row both flags default to False; that's the
    # correct "before" for an opt-in.
    before_email = existing.email_enabled if existing else False
    before_slack = existing.slack_enabled if existing else False

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    if existing is None:
        existing = NotificationPreference(
            id=uuid4(),
            user_id=auth.user_id,
            organization_id=auth.organization_id,
            key=key,
            email_enabled=bool(payload.email_enabled) if payload.email_enabled is not None else False,
            slack_enabled=bool(payload.slack_enabled) if payload.slack_enabled is not None else False,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
    else:
        if payload.email_enabled is not None:
            existing.email_enabled = payload.email_enabled
        if payload.slack_enabled is not None:
            existing.slack_enabled = payload.slack_enabled
        existing.updated_at = now

    # Audit. Notification opt-out is GDPR / VN-personal-data-law
    # adjacent — we want a record of when a user enabled or disabled
    # a channel. `before` / `after` carry only the flags the request
    # actually touched so the activity feed renders "Alice turned email
    # ON for scraper_drift" cleanly.
    from services.audit import record as record_audit

    before_diff: dict[str, bool] = {}
    after_diff: dict[str, Any] = {"key": existing.key}
    if payload.email_enabled is not None:
        before_diff["email_enabled"] = before_email
        after_diff["email_enabled"] = existing.email_enabled
    if payload.slack_enabled is not None:
        before_diff["slack_enabled"] = before_slack
        after_diff["slack_enabled"] = existing.slack_enabled

    await record_audit(
        db,
        organization_id=auth.organization_id,
        actor_user_id=auth.user_id,
        action="notifications.preference.update",
        resource_type="notification_preference",
        resource_id=existing.id,
        before=before_diff,
        after=after_diff,
    )

    await db.commit()
    await db.refresh(existing)
    return ok(NotificationPreferenceOut.model_validate(existing).model_dump(mode="json"))
