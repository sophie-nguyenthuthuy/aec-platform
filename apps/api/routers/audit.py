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

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import paginated
from db.deps import get_db
from db.session import TenantAwareSession
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role
from schemas.audit import AuditEventOut
from services.audit_export import export_csv, export_xlsx, max_export_rows

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/events")
async def list_audit_events(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    action: str | None = None,
    actor_kind: Annotated[str | None, Query(pattern="^(user|api_key|system)$")] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Recent audit events for the caller's org. Admin/owner only.

    Filter params compose: pass `resource_type=change_orders` +
    `resource_id=<uuid>` to see one CO's full audit trail; pass `action`
    to scope to one verb (e.g. `org.member.role_change`).

    `actor_kind` narrows by what KIND of actor produced the row:
      * `user` — human, attributed via `actor_user_id`.
      * `api_key` — programmatic, attributed via `actor_api_key_id`.
        Customer Success uses this to answer "what did partner X's
        integration do this week."
      * `system` — both columns NULL; cron / queue worker actors.
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
    if actor_kind == "user":
        where_clauses.append("actor_user_id IS NOT NULL")
    elif actor_kind == "api_key":
        where_clauses.append("actor_api_key_id IS NOT NULL")
    elif actor_kind == "system":
        where_clauses.append("actor_user_id IS NULL AND actor_api_key_id IS NULL")

    where_sql = " AND ".join(where_clauses)

    # Total first so the meta block reports the unbounded count.
    total_q = await db.execute(
        text(f"SELECT count(*) FROM audit_events WHERE {where_sql}"),
        params,
    )
    total = total_q.scalar_one()

    # Join to `users` for human actors and to `api_keys` for api-key
    # actors. Both joins are LEFT because at most one of the two FK
    # columns is populated on any row (and both are NULL for cron /
    # system events). The `api_key:<name>` prefix on the displayed
    # email keeps the column human-readable while making it obvious in
    # the admin UI that the actor wasn't a person.
    rows = (
        (
            await db.execute(
                text(
                    f"""
                    SELECT
                        a.id, a.organization_id,
                        a.actor_user_id, a.actor_api_key_id,
                        COALESCE(u.email, 'api_key:' || ak.name) AS actor_email,
                        a.action, a.resource_type, a.resource_id,
                        a.before, a.after, a.ip, a.user_agent,
                        a.created_at
                    FROM audit_events a
                    LEFT JOIN users u ON u.id = a.actor_user_id
                    LEFT JOIN api_keys ak ON ak.id = a.actor_api_key_id
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


# ---------- KTNN export endpoints ----------
#
# Vietnamese State Audit Office (Kiểm toán Nhà nước) reviews of SOE
# construction projects routinely demand a date-range export of the
# audit trail. The endpoints below build a CSV (cheap, streamable) or
# an XLSX with a Provenance sheet (legal-admissibility hash) so the
# auditor can take the file offline and analyse in Excel. See
# `services/audit_export.py` for the format details.


@router.get("/export.csv")
async def export_audit_csv(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    since: Annotated[datetime, Query(description="ISO-8601 start (inclusive)")],
    until: Annotated[datetime, Query(description="ISO-8601 end (exclusive)")],
    resource_type: Annotated[str | None, Query()] = None,
):
    """Download the org's audit trail for `[since, until)` as a CSV.

    Vietnamese-language column headers. Capped at
    `services.audit_export.max_export_rows()` (250k) per call — wider
    queries return the first N rows; ask the auditor to narrow the
    range.
    """
    if until <= since:
        raise HTTPException(400, "until_must_be_after_since")

    async with TenantAwareSession(auth.organization_id) as session:
        body, count = await export_csv(
            session=session,
            organization_id=auth.organization_id,
            since=since,
            until=until,
            resource_type=resource_type,
        )

    filename = f"aec-audit-{since.date().isoformat()}-to-{until.date().isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AEC-Audit-Rows": str(count),
            "X-AEC-Audit-Cap": str(max_export_rows()),
        },
    )


@router.get("/export.xlsx")
async def export_audit_xlsx(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    since: Annotated[datetime, Query(description="ISO-8601 start (inclusive)")],
    until: Annotated[datetime, Query(description="ISO-8601 end (exclusive)")],
    resource_type: Annotated[str | None, Query()] = None,
):
    """Download the org's audit trail for `[since, until)` as an XLSX.

    Adds a second sheet (`Provenance`) with the org name, date range,
    row count, and a SHA-256 digest of the equivalent CSV body — the
    legal-admissibility hook for KTNN inspectors who want to verify
    later that the file wasn't tampered with after generation.
    """
    if until <= since:
        raise HTTPException(400, "until_must_be_after_since")

    # Fetch the org name for the Provenance sheet. Single small SELECT,
    # done outside the tenant session to avoid contention with the
    # bigger audit query.
    async with TenantAwareSession(auth.organization_id) as session:
        org = (
            await session.execute(
                text("SELECT name FROM organizations WHERE id = :id"),
                {"id": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        org_name = org or "(unknown)"

        body, count = await export_xlsx(
            session=session,
            organization_id=auth.organization_id,
            organization_name=org_name,
            requester_email=auth.email,
            since=since,
            until=until,
            resource_type=resource_type,
        )

    filename = f"aec-audit-{since.date().isoformat()}-to-{until.date().isoformat()}.xlsx"
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AEC-Audit-Rows": str(count),
            "X-AEC-Audit-Cap": str(max_export_rows()),
        },
    )
