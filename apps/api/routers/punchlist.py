"""Punch list FastAPI router — owner walkthrough findings + per-item workflow.

Endpoints under /api/v1/punchlist:

  * POST   /lists                    — create a punch list (one per walkthrough)
  * GET    /lists                    — list with cheap counters per row
  * GET    /lists/{id}               — detail with nested items
  * PATCH  /lists/{id}               — update header
  * POST   /lists/{id}/sign-off      — owner signs off, status → signed_off
  * POST   /lists/{id}/items         — add item (auto-numbered)
  * PATCH  /items/{id}               — update item (status timestamps auto-stamp)
  * DELETE /items/{id}

The auto-numbering is per-list (1, 2, 3, ...) and survives item deletion —
deleting item #5 leaves a gap, owners refer to numbers in walkthroughs and
re-numbering would be confusing. Race-safe via a unique constraint on
(list_id, item_number); concurrent creates retry the SELECT MAX().
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.punchlist import (
    PhotoHint,
    PhotoHintsResponse,
    PunchItem,
    PunchItemCreate,
    PunchItemStatus,
    PunchItemUpdate,
    PunchList,
    PunchListCreate,
    PunchListDetail,
    PunchListStatus,
    PunchListUpdate,
    SignOffRequest,
)

router = APIRouter(prefix="/api/v1/punchlist", tags=["punchlist"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


# ---------- Lists ----------


@router.post("/lists", status_code=status.HTTP_201_CREATED)
async def create_list(
    payload: PunchListCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO punch_lists
                  (organization_id, project_id, name, walkthrough_date,
                   owner_attendees, notes, created_by)
                VALUES
                  (:org, :pid, :name, :date, :attendees, :notes, :created_by)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "pid": str(payload.project_id),
                    "name": payload.name,
                    "date": payload.walkthrough_date,
                    "attendees": payload.owner_attendees,
                    "notes": payload.notes,
                    "created_by": str(auth.user_id),
                },
            )
        ).one()
        await session.commit()
    base = _row_to_dict(row)
    base.update({"total_items": 0, "open_items": 0, "fixed_items": 0, "verified_items": 0})
    return ok(PunchList.model_validate(base).model_dump(mode="json"))


@router.get("/lists")
async def list_lists(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    status_filter: PunchListStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    where = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(auth.organization_id)}
    if project_id:
        where.append("project_id = :pid")
        params["pid"] = str(project_id)
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter.value
    where_sql = " AND ".join(where)

    async with TenantAwareSession(auth.organization_id) as session:
        total = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM punch_lists WHERE {where_sql}"),
                params,
            )
        ).scalar_one()
        rows = (
            await session.execute(
                text(
                    f"""
                SELECT
                  l.*,
                  (SELECT COUNT(*) FROM punch_items i WHERE i.list_id = l.id) AS total_items,
                  (SELECT COUNT(*) FROM punch_items i
                     WHERE i.list_id = l.id AND i.status IN ('open', 'in_progress')) AS open_items,
                  (SELECT COUNT(*) FROM punch_items i
                     WHERE i.list_id = l.id AND i.status = 'fixed') AS fixed_items,
                  (SELECT COUNT(*) FROM punch_items i
                     WHERE i.list_id = l.id AND i.status = 'verified') AS verified_items
                FROM punch_lists l
                WHERE {where_sql}
                ORDER BY walkthrough_date DESC, created_at DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).all()

    items = [PunchList.model_validate(_row_to_dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=int(total or 0))


@router.get("/lists/{list_id}")
async def get_list(
    list_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        head = (
            await session.execute(
                text(
                    """
                SELECT
                  l.*,
                  (SELECT COUNT(*) FROM punch_items i WHERE i.list_id = l.id) AS total_items,
                  (SELECT COUNT(*) FROM punch_items i
                     WHERE i.list_id = l.id AND i.status IN ('open', 'in_progress')) AS open_items,
                  (SELECT COUNT(*) FROM punch_items i
                     WHERE i.list_id = l.id AND i.status = 'fixed') AS fixed_items,
                  (SELECT COUNT(*) FROM punch_items i
                     WHERE i.list_id = l.id AND i.status = 'verified') AS verified_items
                FROM punch_lists l WHERE id = :id
                """
                ),
                {"id": str(list_id)},
            )
        ).one_or_none()
        if head is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch list not found")
        items = (
            await session.execute(
                text(
                    """
                SELECT * FROM punch_items
                WHERE list_id = :id
                ORDER BY item_number ASC
                """
                ),
                {"id": str(list_id)},
            )
        ).all()

    detail = PunchListDetail(
        list=PunchList.model_validate(_row_to_dict(head)),
        items=[PunchItem.model_validate(_row_to_dict(i)) for i in items],
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/lists/{list_id}")
async def update_list(
    list_id: UUID,
    payload: PunchListUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    if "status" in fields and hasattr(fields["status"], "value"):
        fields["status"] = fields["status"].value
    set_sql = ", ".join(f"{k} = :{k}" for k in fields)

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(f"UPDATE punch_lists SET {set_sql}, updated_at = NOW() WHERE id = :id RETURNING *"),
                {**fields, "id": str(list_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch list not found")
        await session.commit()
    base = _row_to_dict(row)
    base.update({"total_items": 0, "open_items": 0, "fixed_items": 0, "verified_items": 0})
    return ok(PunchList.model_validate(base).model_dump(mode="json"))


@router.post("/lists/{list_id}/sign-off")
async def sign_off(
    list_id: UUID,
    payload: SignOffRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Owner signs off a punch list. All items must be `verified` or
    `waived` — open/in-progress/fixed items block sign-off so a partial
    completion doesn't accidentally close the package."""
    async with TenantAwareSession(auth.organization_id) as session:
        unfinished = (
            await session.execute(
                text(
                    """
                SELECT COUNT(*) FROM punch_items
                WHERE list_id = :id
                  AND status NOT IN ('verified', 'waived')
                """
                ),
                {"id": str(list_id)},
            )
        ).scalar_one()
        if int(unfinished or 0) > 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{unfinished} item(s) still unfinished — verify or waive them before sign-off",
            )

        row = (
            await session.execute(
                text(
                    """
                UPDATE punch_lists
                SET status = 'signed_off',
                    signed_off_at = NOW(),
                    signed_off_by = :user,
                    notes = COALESCE(:notes, notes),
                    updated_at = NOW()
                WHERE id = :id
                RETURNING *
                """
                ),
                {
                    "user": str(auth.user_id),
                    "notes": payload.notes,
                    "id": str(list_id),
                },
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch list not found")
        await session.commit()
    base = _row_to_dict(row)
    base.update({"total_items": 0, "open_items": 0, "fixed_items": 0, "verified_items": 0})
    return ok(PunchList.model_validate(base).model_dump(mode="json"))


# ---------- Items ----------


@router.post("/lists/{list_id}/items", status_code=status.HTTP_201_CREATED)
async def add_item(
    list_id: UUID,
    payload: PunchItemCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        # Auto-number per list. Race with concurrent inserts is caught by
        # the unique (list_id, item_number) constraint — the second writer
        # gets a 409 from the DB and the caller can retry.
        next_n = (
            await session.execute(
                text(
                    """
                SELECT COALESCE(MAX(item_number), 0) + 1
                FROM punch_items WHERE list_id = :id
                """
                ),
                {"id": str(list_id)},
            )
        ).scalar_one()
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO punch_items
                  (organization_id, list_id, item_number, description, location,
                   trade, severity, photo_id, assigned_user_id, due_date, notes)
                VALUES
                  (:org, :lid, :n, :desc, :loc, :trade, :sev, :photo, :assignee,
                   :due, :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "lid": str(list_id),
                    "n": int(next_n),
                    "desc": payload.description,
                    "loc": payload.location,
                    "trade": payload.trade.value,
                    "sev": payload.severity.value,
                    "photo": str(payload.photo_id) if payload.photo_id else None,
                    "assignee": (str(payload.assigned_user_id) if payload.assigned_user_id else None),
                    "due": payload.due_date,
                    "notes": payload.notes,
                },
            )
        ).one()
        await session.commit()
    return ok(PunchItem.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.patch("/items/{item_id}")
async def update_item(
    item_id: UUID,
    payload: PunchItemUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Update a punch item. Status transitions auto-stamp the corresponding
    timestamp:
      * status='fixed' sets `fixed_at = NOW()` (if null)
      * status='verified' sets `verified_at = NOW()` + `verified_by = current user`
    """
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    for k in ("trade", "severity", "status"):
        if k in fields and hasattr(fields[k], "value"):
            fields[k] = fields[k].value
    if "photo_id" in fields and fields["photo_id"] is not None:
        fields["photo_id"] = str(fields["photo_id"])
    if "assigned_user_id" in fields and fields["assigned_user_id"] is not None:
        fields["assigned_user_id"] = str(fields["assigned_user_id"])

    extra_set = ""
    target_status = fields.get("status")
    if target_status == PunchItemStatus.fixed.value:
        extra_set = ", fixed_at = COALESCE(fixed_at, NOW())"
    elif target_status == PunchItemStatus.verified.value:
        extra_set = ", verified_at = NOW(), verified_by = :verifier"

    set_sql = ", ".join(f"{k} = :{k}" for k in fields)
    params: dict[str, Any] = {**fields, "id": str(item_id)}
    if target_status == PunchItemStatus.verified.value:
        params["verifier"] = str(auth.user_id)

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(f"UPDATE punch_items SET {set_sql}, updated_at = NOW(){extra_set} WHERE id = :id RETURNING *"),
                params,
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch item not found")
        await session.commit()
    return ok(PunchItem.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text("DELETE FROM punch_items WHERE id = :id"),
            {"id": str(item_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch item not found")
        await session.commit()


# ---------- SiteEye photo hints ----------


@router.get("/lists/{list_id}/photo-hints")
async def photo_hints(
    list_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    window_days: int = Query(default=2, ge=0, le=14),
    limit: int = Query(default=12, ge=1, le=50),
):
    """SiteEye photos taken on the project around the walkthrough date.

    The supervisor uses these as candidates to attach to new punch items —
    in real walkthroughs, the owner (or supervisor) is also taking photos
    on a phone-connected camera that hits SiteEye, so the photos and the
    findings co-occur. We surface the recent ones as one-click "attach
    this" chips on the add-item dialog.

    `window_days` covers a few days on either side of the walkthrough so a
    list created the morning after a walkthrough still finds the photos.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        list_row = (
            await session.execute(
                text("SELECT project_id, walkthrough_date FROM punch_lists WHERE id = :id"),
                {"id": str(list_id)},
            )
        ).one_or_none()
        if list_row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch list not found")
        ld = _row_to_dict(list_row)
        rows = (
            await session.execute(
                text(
                    """
                SELECT id AS photo_id, file_id, taken_at, thumbnail_url,
                       safety_status, tags
                FROM site_photos
                WHERE project_id = :pid
                  AND taken_at IS NOT NULL
                  AND taken_at::date BETWEEN :from_d AND :to_d
                ORDER BY taken_at DESC
                LIMIT :limit
                """
                ),
                {
                    "pid": str(ld["project_id"]),
                    "from_d": ld["walkthrough_date"],
                    "to_d": ld["walkthrough_date"],
                    # Postgres doesn't accept named-param arithmetic in BETWEEN —
                    # widen via SQL interval below.
                    "limit": limit,
                },
            )
        ).all()
        # If the strict same-day query found nothing, broaden the window.
        if not rows and window_days > 0:
            rows = (
                await session.execute(
                    text(
                        """
                    SELECT id AS photo_id, file_id, taken_at, thumbnail_url,
                           safety_status, tags
                    FROM site_photos
                    WHERE project_id = :pid
                      AND taken_at IS NOT NULL
                      AND taken_at::date BETWEEN
                          (:walkthrough_date::date - (:window_days || ' days')::interval)
                          AND
                          (:walkthrough_date::date + (:window_days || ' days')::interval)
                    ORDER BY taken_at DESC
                    LIMIT :limit
                    """
                    ),
                    {
                        "pid": str(ld["project_id"]),
                        "walkthrough_date": ld["walkthrough_date"],
                        "window_days": window_days,
                        "limit": limit,
                    },
                )
            ).all()

    hints = [
        PhotoHint(
            photo_id=r._mapping["photo_id"],
            file_id=r._mapping.get("file_id"),
            taken_at=r._mapping.get("taken_at"),
            thumbnail_url=r._mapping.get("thumbnail_url"),
            safety_status=r._mapping.get("safety_status"),
            tags=list(r._mapping.get("tags") or []),
        )
        for r in rows
    ]
    return ok(
        PhotoHintsResponse(
            list_id=list_id,
            walkthrough_date=ld["walkthrough_date"],
            window_days=window_days,
            results=hints,
        ).model_dump(mode="json")
    )
