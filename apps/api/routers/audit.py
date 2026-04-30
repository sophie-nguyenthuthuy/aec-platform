"""Audit-log query endpoint.

Read-only — the audit log is append-only by design (see migration
0022_audit_events). Admin-gated because raw audit content can leak
who-touched-what across teams; even in small orgs, only owners /
admins should see e.g. "Bob demoted Alice from admin".

Filters mirror the indexes in the underlying table:
  * `(organization_id, created_at DESC)` covers the default "recent"
    query.
  * `(resource_type, resource_id)` covers the "this object's history"
    drill-down.

For deeper historical queries (scrolling > a few hundred events),
pagination is via `limit` + `offset`. Cursor pagination would be
better but isn't worth the schema complexity yet — admins typically
look at the last hour or one specific resource.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import paginated
from db.deps import get_db
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role
from schemas.audit import AuditEventOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/events")
async def list_audit_events(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Recent audit events for the caller's org. Admin/owner only.

    Filter params compose: pass `resource_type=change_orders` +
    `resource_id=<uuid>` to see one CO's full audit trail; pass `action`
    to scope to one verb (e.g. `org.member.role_change`).
    """
    where_clauses = ["organization_id = :org"]
    params: dict[str, object] = {"org": str(auth.organization_id)}
    if resource_type:
        where_clauses.append("resource_type = :rtype")
        params["rtype"] = resource_type
    if resource_id:
        where_clauses.append("resource_id = :rid")
        params["rid"] = str(resource_id)
    if action:
        where_clauses.append("action = :action")
        params["action"] = action

    where_sql = " AND ".join(where_clauses)

    # Total first so the meta block reports the unbounded count.
    total_q = await db.execute(
        text(f"SELECT count(*) FROM audit_events WHERE {where_sql}"),
        params,
    )
    total = total_q.scalar_one()

    # Join to `users` to surface the actor's email — the audit row only
    # carries the FK. LEFT JOIN because actor_user_id is nullable
    # (system-driven events).
    rows = (
        (
            await db.execute(
                text(
                    f"""
                    SELECT
                        a.id, a.organization_id, a.actor_user_id,
                        u.email AS actor_email,
                        a.action, a.resource_type, a.resource_id,
                        a.before, a.after, a.ip, a.user_agent,
                        a.created_at
                    FROM audit_events a
                    LEFT JOIN users u ON u.id = a.actor_user_id
                    WHERE {where_sql}
                    ORDER BY a.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )

    items = [AuditEventOut.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(
        items,
        page=(offset // limit) + 1 if limit else 1,
        per_page=limit,
        total=int(total or 0),
    )
