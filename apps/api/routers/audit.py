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

Two endpoints:
  * `GET /events`        — paginated JSON for the dashboard.
  * `GET /events.csv`    — streaming CSV for compliance review +
                           offline analysis. Same filter surface;
                           capped at `_CSV_MAX_ROWS`.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import paginated
from db.deps import get_db
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role
from schemas.audit import AuditEventOut

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# Hard cap on the CSV export — 50k matches the retention prune cap
# idiom and keeps the streaming response under ~30MB even with
# verbose before/after JSON. Exceeding rows return 413 with a hint
# to tighten the date range, not silently truncate (a half-CSV
# would mislead a compliance reviewer who reads the file as
# authoritative).
_CSV_MAX_ROWS = 50_000


def _build_where(
    *,
    organization_id: UUID,
    resource_type: str | None,
    resource_id: UUID | None,
    action: str | None,
    actor_kind: str | None,
    since_days: int | None,
) -> tuple[str, dict[str, Any]]:
    """Shared WHERE-clause builder for both the JSON list endpoint and
    the CSV export. Pulled out so the two endpoints stay in lock-step
    on filter semantics — a divergence (e.g. CSV missing the
    actor_kind filter) would mean a compliance reviewer's CSV doesn't
    match what the dashboard shows for the same filter set.

    Returns `(where_sql, params)` where `where_sql` is the SQL
    fragment to interpolate after `WHERE` and `params` is the bound-
    params dict the caller passes to `session.execute`.
    """
    where_clauses = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(organization_id)}
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
    if since_days is not None:
        where_clauses.append("created_at >= NOW() - make_interval(days => :since_days)")
        params["since_days"] = since_days
    return (" AND ".join(where_clauses), params)


@router.get("/events")
async def list_audit_events(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    action: str | None = None,
    actor_kind: Annotated[str | None, Query(pattern="^(user|api_key|system)$")] = None,
    since_days: Annotated[int | None, Query(ge=1, le=365)] = None,
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

    `since_days` narrows to rows with
    `created_at >= NOW() - INTERVAL 'N days'`. Drives the dashboard
    quick-chip row (24h / 7d / 30d / all). Optional — omitting it
    preserves the historical "everything in retention window"
    behaviour.
    """
    where_sql, params = _build_where(
        organization_id=auth.organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        actor_kind=actor_kind,
        since_days=since_days,
    )

    # Total first so the meta block reports the unbounded count.
    total_q = await db.execute(
        text(f"SELECT count(*) FROM audit_events WHERE {where_sql}"),
        params,
    )
    total = total_q.scalar_one()

    # Join to `users` for human actors and to `api_keys` for api-key
    # actors. Both joins are LEFT because at most one of the two FK
    # columns is populated on any row (and both are NULL for cron /
    # system events).
    #
    # We project them as TWO distinct columns rather than coalescing
    # them into one `api_key:<name>` string. The frontend wants to
    # render user emails differently from api-key actors (different
    # icons, the api-key gets a "key" badge), so a single coalesced
    # column would force the frontend to parse the prefix back out.
    # Keeping them separate is wire-clean.
    rows = (
        (
            await db.execute(
                text(
                    f"""
                    SELECT
                        a.id, a.organization_id,
                        a.actor_user_id, a.actor_api_key_id,
                        u.email                    AS actor_email,
                        ak.name                    AS actor_api_key_name,
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


# ---------- CSV export (cycle P3) ----------


# Column order in the CSV — pin so a refactor can't accidentally reorder
# (compliance reviewers' downstream pipelines key off the header line).
# Headers are deliberately user-friendly ("when") rather than DB-y
# ("created_at") so a CSV opened in Excel reads cleanly without the
# reviewer needing the schema docs.
_CSV_COLUMNS: list[tuple[str, str]] = [
    # (csv_header, source_key_in_row)
    ("when", "created_at"),
    ("action", "action"),
    ("resource_type", "resource_type"),
    ("resource_id", "resource_id"),
    ("actor_email", "actor_email"),
    ("actor_api_key_name", "actor_api_key_name"),
    ("actor_kind", "_actor_kind"),  # synthesised
    ("ip", "ip"),
    ("user_agent", "user_agent"),
    ("before", "_before_json"),  # JSON-serialised
    ("after", "_after_json"),  # JSON-serialised
]


@router.get("/events.csv")
async def export_audit_events_csv(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    action: str | None = None,
    actor_kind: Annotated[str | None, Query(pattern="^(user|api_key|system)$")] = None,
    since_days: Annotated[int | None, Query(ge=1, le=365)] = None,
):
    """Stream a CSV of the matching audit events.

    Same filter surface as `GET /events` so a reviewer can preview in
    the dashboard, then click "Download CSV" with the same chips
    selected and get the same row set.

    Capped at `_CSV_MAX_ROWS` (50k). Larger windows return 413 with a
    hint to tighten — silently truncating would mislead a compliance
    reviewer who reads the file as authoritative ("you sent us 50k
    rows, but they're not the 50k I asked for").

    Streaming via `StreamingResponse`: even at 50k × ~600 bytes/row
    the body is ~30MB; streaming means we don't materialise it all
    in Python memory at once. Each row is yielded as the CSV writer
    flushes its internal buffer.

    Why not server-side gzip: compliance reviewers often open these
    in Excel directly; the extra .gz step adds friction. The body
    is plain-text CSV with the standard `text/csv; charset=utf-8`
    Content-Type and a `Content-Disposition: attachment` so the
    browser saves it without an open-in-tab fallback.

    Why not background job + email link: the row cap keeps it under
    a 30s request budget on a healthy DB. If a future customer asks
    for unbounded exports we add a `request_export` job + email; for
    v1 the synchronous path covers every realistic compliance ask.
    """
    where_sql, params = _build_where(
        organization_id=auth.organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        actor_kind=actor_kind,
        since_days=since_days,
    )

    # Count first so we can 413 BEFORE running the heavy SELECT. A
    # reviewer asking for 6 months of audit on a busy org sees a
    # clear "tighten the range" message instead of a 30s wait that
    # ends in a row-truncated CSV.
    total_q = await db.execute(
        text(f"SELECT count(*) FROM audit_events WHERE {where_sql}"),
        params,
    )
    total = int(total_q.scalar_one() or 0)
    if total > _CSV_MAX_ROWS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            (
                f"Export would include {total:,} rows; cap is {_CSV_MAX_ROWS:,}. "
                "Tighten the date range (`since_days`) or filter by action / "
                "resource_type to bring the count below the cap."
            ),
        )

    # SAME projection as the JSON endpoint so the CSV header set
    # matches what the dashboard renders.
    rows_q = await db.execute(
        text(
            f"""
            SELECT
                a.id, a.organization_id,
                a.actor_user_id, a.actor_api_key_id,
                u.email   AS actor_email,
                ak.name   AS actor_api_key_name,
                a.action, a.resource_type, a.resource_id,
                a.before, a.after, a.ip, a.user_agent,
                a.created_at
            FROM audit_events a
            LEFT JOIN users u ON u.id = a.actor_user_id
            LEFT JOIN api_keys ak ON ak.id = a.actor_api_key_id
            WHERE {where_sql}
            ORDER BY a.created_at DESC
            LIMIT :cap
            """
        ),
        {**params, "cap": _CSV_MAX_ROWS},
    )
    rows = rows_q.mappings().all()

    def _row_dict(r: Any) -> dict[str, Any]:
        # Synthesise the three computed columns from the raw row.
        # `_actor_kind` mirrors the API filter vocabulary.
        if r["actor_user_id"] is not None:
            actor_kind_val = "user"
        elif r["actor_api_key_id"] is not None:
            actor_kind_val = "api_key"
        else:
            actor_kind_val = "system"
        return {
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            "action": r["action"] or "",
            "resource_type": r["resource_type"] or "",
            "resource_id": str(r["resource_id"]) if r["resource_id"] else "",
            "actor_email": r["actor_email"] or "",
            "actor_api_key_name": r["actor_api_key_name"] or "",
            "_actor_kind": actor_kind_val,
            "ip": r["ip"] or "",
            "user_agent": r["user_agent"] or "",
            # JSON-serialise so the cell holds the full diff. Excel
            # treats it as a string; jq / pandas can re-parse via
            # `json.loads`.
            "_before_json": json.dumps(r["before"], default=str, ensure_ascii=False),
            "_after_json": json.dumps(r["after"], default=str, ensure_ascii=False),
        }

    def _stream():
        # Use io.StringIO + csv.writer rather than f-strings: the csv
        # module handles RFC 4180 quoting (commas, newlines, embedded
        # quotes). Hand-rolling that escape logic is the kind of bug
        # that makes its way into Excel as "every other row is
        # broken".
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([h for h, _src in _CSV_COLUMNS])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()

        for r in rows:
            d = _row_dict(r)
            writer.writerow([d[src] for _h, src in _CSV_COLUMNS])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    # `attachment` so browsers save rather than display. Filename
    # encodes the org id + timestamp so a reviewer downloading from
    # multiple tenants doesn't accidentally overwrite.
    from datetime import UTC
    from datetime import datetime as _dt

    stamp = _dt.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"audit-{auth.organization_id}-{stamp}.csv"
    return StreamingResponse(
        _stream(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Tell intermediaries not to cache — the row set drifts on
            # every new audit row.
            "Cache-Control": "no-store",
        },
    )
