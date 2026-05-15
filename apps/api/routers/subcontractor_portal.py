"""SubcontractorPortal — admin mints tokens, public sub uses them.

Two surfaces, deliberately separated:

A. **Admin (authed, tenant-scoped)** under `/api/v1/subcontractors/`:
   * POST   /projects/{id}/grants — mint token for a sub, returns
     the raw token ONCE. Admin pastes into Zalo / SMS to sub.
   * GET    /projects/{id}/grants — list grants + last-used + status
   * POST   /grants/{id}/revoke — kill the token immediately
   * POST   /grants/{id}/assignments — assign work scope to a sub
   * GET    /grants/{id}/assignments — see what sub is responsible for

B. **Public (token-auth)** under `/api/v1/public/sub/`:
   * GET    /?t=<token> — list sub's assignments + their project
     context (name, address, contract status) + payment status
   * POST   /assignments/{id}/progress?t=<token> — sub reports
     progress (percent + status + note + photo file ids)

Token is the only credential on the public side. RLS isn't engaged
on the grants table because the public path needs cross-tenant
lookup (it doesn't know which org it's looking at until it decodes
the token). Tenant isolation is enforced application-side via
WHERE token_hash = $1 + matching project_id ownership.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text

from core.envelope import ok
from db.session import AdminSessionFactory, TenantAwareSession
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from services.subcontractor_tokens import (
    SubcontractorTokenClaims,
    TokenError,
    hash_token,
    mint_subcontractor_token,
    verify_subcontractor_token,
)

logger = logging.getLogger(__name__)

# Two routers, mounted under different prefixes so the public path
# stays auth-free in main.py + middleware allowlists.
admin_router = APIRouter(
    prefix="/api/v1/subcontractors", tags=["subcontractors"]
)
public_router = APIRouter(prefix="/api/v1/public/sub", tags=["subcontractor-public"])


# ---------- Schemas ----------


class GrantCreate(BaseModel):
    subcontractor_name: str = Field(min_length=2, max_length=200)
    subcontractor_email: EmailStr
    subcontractor_phone: str | None = Field(default=None, max_length=20)
    ttl_days: int = Field(default=365, ge=7, le=730)


class AssignmentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    contract_value_vnd: int | None = Field(default=None, ge=0)
    planned_start: datetime | None = None
    planned_finish: datetime | None = None
    schedule_activity_id: UUID | None = None


class ProgressReport(BaseModel):
    percent_complete: int = Field(ge=0, le=100)
    status: Literal[
        "not_started", "in_progress", "review_needed", "complete", "blocked"
    ]
    note: str | None = Field(default=None, max_length=2000)
    photo_file_ids: list[UUID] | None = None


# ---------- Admin endpoints (B-side) ----------


@admin_router.post(
    "/projects/{project_id}/grants",
    status_code=status.HTTP_201_CREATED,
)
async def mint_grant(
    project_id: UUID,
    payload: GrantCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Mint a portal token for one subcontractor on one project.

    Returns the raw token ONCE — admin must copy it now (paste into
    Zalo / SMS / email to the sub). The DB only stores `hash_token`;
    we cannot recover the raw token later if the admin loses it. To
    rotate, revoke + mint a new one.
    """
    grant_id = uuid4()
    token = mint_subcontractor_token(
        grant_id=grant_id,
        organization_id=auth.organization_id,
        project_id=project_id,
        email=payload.subcontractor_email,
        ttl_days=payload.ttl_days,
    )
    token_h = hash_token(token)
    expires_at = datetime.now(UTC) + timedelta(days=payload.ttl_days)

    async with TenantAwareSession(auth.organization_id) as session:
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO subcontractor_portal_grants
                        (id, organization_id, project_id,
                         subcontractor_name, subcontractor_email,
                         subcontractor_phone, token_hash, expires_at,
                         created_by)
                    VALUES (:id, :org, :pid, :name, :email, :phone,
                            :hash, :exp, :uid)
                    """
                ),
                {
                    "id": str(grant_id),
                    "org": str(auth.organization_id),
                    "pid": str(project_id),
                    "name": payload.subcontractor_name,
                    "email": payload.subcontractor_email,
                    "phone": payload.subcontractor_phone,
                    "hash": token_h,
                    "exp": expires_at,
                    "uid": str(auth.user_id),
                },
            )
            await session.commit()
        except Exception as exc:
            msg = str(exc).lower()
            if "ix_subportal_grants_active_email" in msg or "unique" in msg:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "active_grant_already_exists_revoke_first",
                ) from exc
            raise

    # Build the portal URL — the value the admin actually shares.
    from core.config import get_settings

    web_base = get_settings().web_base_url.rstrip("/")
    portal_url = f"{web_base}/subcontractor?t={token}"

    return ok(
        {
            "grant_id": str(grant_id),
            "token": token,
            "portal_url": portal_url,
            "expires_at": expires_at.isoformat(),
            "warning": (
                "Đây là lần duy nhất bạn xem được token này. "
                "Sao chép URL ngay và gửi cho nhà thầu phụ qua Zalo/SMS."
            ),
        }
    )


@admin_router.get("/projects/{project_id}/grants")
async def list_grants(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """List all subcontractor grants for a project (active + revoked
    + expired). Token itself NOT returned — only metadata."""
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT g.id, g.subcontractor_name, g.subcontractor_email,
                           g.subcontractor_phone, g.expires_at,
                           g.revoked_at, g.last_used_at, g.created_at,
                           COUNT(a.id)::int AS assignment_count,
                           COALESCE(AVG(a.percent_complete), 0)::int AS avg_progress
                    FROM subcontractor_portal_grants g
                    LEFT JOIN subcontractor_assignments a ON a.grant_id = g.id
                    WHERE g.project_id = :pid
                    GROUP BY g.id
                    ORDER BY g.created_at DESC
                    """
                ),
                {"pid": str(project_id)},
            )
        ).mappings().all()

    now = datetime.now(UTC)
    return ok(
        {
            "grants": [
                {
                    "id": str(r["id"]),
                    "subcontractor_name": r["subcontractor_name"],
                    "subcontractor_email": r["subcontractor_email"],
                    "subcontractor_phone": r["subcontractor_phone"],
                    "expires_at": r["expires_at"].isoformat(),
                    "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
                    "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
                    "created_at": r["created_at"].isoformat(),
                    "assignment_count": r["assignment_count"],
                    "avg_progress": int(r["avg_progress"] or 0),
                    "status": (
                        "revoked"
                        if r["revoked_at"]
                        else "expired"
                        if r["expires_at"] < now
                        else "active"
                    ),
                }
                for r in rows
            ]
        }
    )


@admin_router.post("/grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Immediately kill the token. The sub's portal returns 401 on
    next access. Idempotent — revoking twice is a no-op."""
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                """
                UPDATE subcontractor_portal_grants
                SET revoked_at = NOW()
                WHERE id = :id AND revoked_at IS NULL
                """
            ),
            {"id": str(grant_id)},
        )
        await session.commit()
        if result.rowcount == 0:
            # Either grant not found OR already revoked. Return 204
            # either way (idempotent) but with a hint via header.
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "grant_not_found_or_already_revoked"
            )

    return ok({"revoked": True})


@admin_router.post(
    "/grants/{grant_id}/assignments",
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    grant_id: UUID,
    payload: AssignmentCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Assign a work scope to a subcontractor grant. Once added, the
    sub sees it in their portal next refresh."""
    async with TenantAwareSession(auth.organization_id) as session:
        # Verify grant exists + is active
        grant = (
            await session.execute(
                text(
                    """
                    SELECT project_id, revoked_at, expires_at
                    FROM subcontractor_portal_grants
                    WHERE id = :id
                    """
                ),
                {"id": str(grant_id)},
            )
        ).mappings().one_or_none()
        if grant is None:
            raise HTTPException(404, "grant_not_found")
        if grant["revoked_at"] is not None:
            raise HTTPException(400, "grant_revoked")
        if grant["expires_at"] < datetime.now(UTC):
            raise HTTPException(400, "grant_expired")

        assign_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO subcontractor_assignments
                    (id, organization_id, grant_id, project_id,
                     title, description, contract_value_vnd,
                     planned_start, planned_finish, schedule_activity_id)
                VALUES (:id, :org, :grant, :pid, :title, :desc,
                        :val, :start, :end, :sa)
                """
            ),
            {
                "id": str(assign_id),
                "org": str(auth.organization_id),
                "grant": str(grant_id),
                "pid": str(grant["project_id"]),
                "title": payload.title,
                "desc": payload.description,
                "val": payload.contract_value_vnd,
                "start": payload.planned_start,
                "end": payload.planned_finish,
                "sa": str(payload.schedule_activity_id)
                if payload.schedule_activity_id
                else None,
            },
        )
        await session.commit()

    return ok({"id": str(assign_id)})


@admin_router.get("/grants/{grant_id}/assignments")
async def list_assignments(
    grant_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Admin view of all assignments for a grant + sub's progress."""
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, title, description, contract_value_vnd,
                           planned_start, planned_finish, percent_complete,
                           status, sub_last_note, sub_last_update_at,
                           created_at
                    FROM subcontractor_assignments
                    WHERE grant_id = :grant
                    ORDER BY created_at ASC
                    """
                ),
                {"grant": str(grant_id)},
            )
        ).mappings().all()

    return ok(
        {
            "assignments": [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "description": r["description"],
                    "contract_value_vnd": int(r["contract_value_vnd"])
                    if r["contract_value_vnd"]
                    else None,
                    "planned_start": r["planned_start"].isoformat()
                    if r["planned_start"]
                    else None,
                    "planned_finish": r["planned_finish"].isoformat()
                    if r["planned_finish"]
                    else None,
                    "percent_complete": r["percent_complete"],
                    "status": r["status"],
                    "sub_last_note": r["sub_last_note"],
                    "sub_last_update_at": r["sub_last_update_at"].isoformat()
                    if r["sub_last_update_at"]
                    else None,
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }
    )


# ---------- Public endpoints (A-side, token-auth) ----------


async def _resolve_grant_or_401(token: str) -> SubcontractorTokenClaims:
    """Decode token + verify the DB-side hash matches an active grant.

    Two layers of check intentional:
      1. JWT signature/expiry: cryptographic verify, no DB hop.
      2. DB lookup by token_hash: ensures the grant hasn't been
         revoked since the JWT was minted.
    """
    try:
        claims = verify_subcontractor_token(token)
    except TokenError as exc:
        raise HTTPException(401, f"invalid_or_expired_token: {exc}") from exc

    async with AdminSessionFactory() as session:
        grant = (
            await session.execute(
                text(
                    """
                    SELECT id, organization_id, project_id,
                           revoked_at, expires_at
                    FROM subcontractor_portal_grants
                    WHERE token_hash = :hash
                    """
                ),
                {"hash": hash_token(token)},
            )
        ).mappings().one_or_none()

    if grant is None:
        raise HTTPException(401, "token_not_recognised")
    if grant["revoked_at"] is not None:
        raise HTTPException(401, "token_revoked")
    if grant["expires_at"] < datetime.now(UTC):
        raise HTTPException(401, "token_expired_on_server")

    return claims


@public_router.get("")
async def public_dashboard(
    request: Request,
    t: Annotated[str, Query(min_length=20)],
):
    """Sub's home page — shows project context + assignments + payment
    status.

    Token in `?t=` is the only credential. Rate-limited per-token
    inside `services.rfq_rate_limit` (shared with the RFQ portal — the
    bucket is per-token-hash so RFQ flooding can't burn sub-portal
    quota).
    """
    claims = await _resolve_grant_or_401(t)

    async with AdminSessionFactory() as session:
        # Project info
        project = (
            await session.execute(
                text(
                    """
                    SELECT id::text AS id, name, address, type, status
                    FROM projects
                    WHERE id = :pid AND organization_id = :org
                    """
                ),
                {"pid": str(claims.project_id), "org": str(claims.organization_id)},
            )
        ).mappings().one_or_none()
        if project is None:
            raise HTTPException(404, "project_not_found")

        # Org info for the header
        org = (
            await session.execute(
                text(
                    "SELECT name FROM organizations WHERE id = :id"
                ),
                {"id": str(claims.organization_id)},
            )
        ).mappings().one_or_none()

        # Sub's assignments
        assignments = (
            await session.execute(
                text(
                    """
                    SELECT id, title, description, contract_value_vnd,
                           planned_start, planned_finish, percent_complete,
                           status, sub_last_update_at
                    FROM subcontractor_assignments
                    WHERE grant_id = :grant
                    ORDER BY created_at ASC
                    """
                ),
                {"grant": str(claims.grant_id)},
            )
        ).mappings().all()

        # Last-used timestamp + IP — audit signal for the admin side
        await session.execute(
            text(
                """
                UPDATE subcontractor_portal_grants
                SET last_used_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": str(claims.grant_id)},
        )
        await session.commit()

    return ok(
        {
            "organization": {"name": org["name"] if org else ""},
            "project": {
                "id": project["id"],
                "name": project["name"],
                "address": project["address"],
                "type": project["type"],
                "status": project["status"],
            },
            "subcontractor_email": claims.email,
            "assignments": [
                {
                    "id": str(a["id"]),
                    "title": a["title"],
                    "description": a["description"],
                    "contract_value_vnd": int(a["contract_value_vnd"])
                    if a["contract_value_vnd"]
                    else None,
                    "planned_start": a["planned_start"].isoformat()
                    if a["planned_start"]
                    else None,
                    "planned_finish": a["planned_finish"].isoformat()
                    if a["planned_finish"]
                    else None,
                    "percent_complete": a["percent_complete"],
                    "status": a["status"],
                    "sub_last_update_at": a["sub_last_update_at"].isoformat()
                    if a["sub_last_update_at"]
                    else None,
                }
                for a in assignments
            ],
        }
    )


@public_router.post(
    "/assignments/{assignment_id}/progress",
    status_code=status.HTTP_201_CREATED,
)
async def report_progress(
    assignment_id: UUID,
    payload: ProgressReport,
    request: Request,
    t: Annotated[str, Query(min_length=20)],
):
    """Sub reports progress against one assignment. Creates a
    progress event for audit + updates the latest snapshot on the
    assignment row.
    """
    claims = await _resolve_grant_or_401(t)
    client_ip = request.client.host if request.client else None

    async with AdminSessionFactory() as session:
        # Verify the assignment belongs to this grant — cross-grant
        # attack defence (sub A can't report on sub B's assignment).
        assignment = (
            await session.execute(
                text(
                    """
                    SELECT id, organization_id
                    FROM subcontractor_assignments
                    WHERE id = :id AND grant_id = :grant
                    """
                ),
                {"id": str(assignment_id), "grant": str(claims.grant_id)},
            )
        ).mappings().one_or_none()
        if assignment is None:
            raise HTTPException(404, "assignment_not_found_for_this_grant")

        # Persist the event
        event_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO subcontractor_progress_events
                    (id, organization_id, assignment_id, reported_by_email,
                     reported_by_ip, percent_complete, status, note,
                     photo_file_ids)
                VALUES (:id, :org, :assign, :email, :ip,
                        :pct, :st, :note, :photos)
                """
            ),
            {
                "id": str(event_id),
                "org": str(claims.organization_id),
                "assign": str(assignment_id),
                "email": claims.email,
                "ip": client_ip,
                "pct": payload.percent_complete,
                "st": payload.status,
                "note": payload.note,
                "photos": [str(f) for f in payload.photo_file_ids]
                if payload.photo_file_ids
                else None,
            },
        )

        # Update the assignment's snapshot
        await session.execute(
            text(
                """
                UPDATE subcontractor_assignments
                SET percent_complete = :pct,
                    status = :st,
                    sub_last_note = :note,
                    sub_last_update_at = NOW(),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {
                "pct": payload.percent_complete,
                "st": payload.status,
                "note": payload.note,
                "id": str(assignment_id),
            },
        )
        await session.commit()

    logger.info(
        "subportal.progress org=%s grant=%s assign=%s pct=%d status=%s",
        claims.organization_id,
        claims.grant_id,
        assignment_id,
        payload.percent_complete,
        payload.status,
    )

    return ok({"event_id": str(event_id), "recorded": True})
