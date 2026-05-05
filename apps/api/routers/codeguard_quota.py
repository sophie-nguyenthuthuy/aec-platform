"""Tenant-facing read endpoints for the CODEGUARD per-org token cap.

Why this is its own module (not a section of `routers/codeguard.py`):

  The mixed-concern parent file (~1300 lines spanning health probes,
  LLM routes, regulation queries, permit checklists, and quota reads)
  has historically been a target for an aggressive local linter pass
  that silently drops large additions. Concentrating the at-risk
  routes into a small focused module (this file) reduces both the
  attack surface and the cost of recovery — when the reverter does
  hit, this file is small enough that a single targeted edit
  restores it.

  The snapshot test (`tests/test_codeguard_surface_snapshot.py`) AND
  the pre-commit hook + CI gate built around it pin the exact set of
  routes registered here. A regression that drops the module from
  the include path (or a route from inside the module) fails the
  gate at PR time with a clear "route X expected but missing"
  message rather than shipping a broken widget.

What lives here:

  * `GET /api/v1/codeguard/quota/audit` — tenant audit log + CSV
    export. Filters compose with AND (limit + since + action +
    cursor); action accepts `quota_set | quota_reset |
    quota_reconcile`. Cursor scheme `(occurred_at, id) DESC` for
    stable pagination over same-timestamp rows.
  * `GET /api/v1/codeguard/quota/top-users` — per-user spend ranking
    for the org's CURRENT period. Surfaces `codeguard_user_usage`
    via the dedicated DESC index. Tenant-scoped, server-clamped to
    1..50.

  `/quota` and `/quota/history` deliberately stay in the parent
  `routers/codeguard.py` — they shipped earlier and have proven
  stable against the reverter; moving them now would be churn for
  no defensive gain.

Wiring: the parent `routers/codeguard.py` calls
`router.include_router(...)` against the `quota_router` exported
here. Both routers share the `/api/v1/codeguard` prefix so the
`/quota/audit` and `/quota/top-users` paths land at the same URL
they did when those routes lived inline.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext, require_auth

# No prefix — this router is mounted via `router.include_router` from
# the parent `routers/codeguard.py`, which already carries the
# `/api/v1/codeguard` prefix. FastAPI concatenates parent + child
# prefixes; double-applying would land routes at `/api/v1/codeguard
# /api/v1/codeguard/quota/audit`. Tag stays so OpenAPI groups these
# under the same "codeguard" section as the parent.
quota_router = APIRouter(tags=["codeguard"])


# ---------- /quota/audit -------------------------------------------------


@quota_router.get("/quota/audit")
async def get_codeguard_quota_audit(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
    since: str | None = None,
    action: str | None = None,
    before: str | None = None,
    format: str = "json",
):
    """Return the caller's org's quota-mutation audit log, most-recent first.

    Tenant-facing surface — closes the loop on "who raised our cap
    last quarter" without filing a support ticket. Org-scoped via
    the FK on `codeguard_quota_audit_log.organization_id`.

    Filters compose with AND, mirroring the CLI's `audit` subcommand:
      * `limit`  — clamped 1..200; default 50.
      * `since`  — ISO date (YYYY-MM-DD); only rows at/after.
      * `action` — `quota_set | quota_reset | quota_reconcile`.
                   `quota_reconcile` rows are emitted by the
                   reconcile cron's remediation path
                   (`scripts/codeguard_quotas.py reconcile
                   --remediate`); admins investigating a cap-cache
                   realignment can filter to just those entries.
      * `before` — pagination cursor `<occurred_at_iso>:<id>`.
                   Returns rows STRICTLY older than this position.

    Cursor scheme: ordered by `(occurred_at DESC, id DESC)` with the
    composite cursor giving lexicographic comparison. Including `id`
    in the cursor handles the rare case of two rows with identical
    `occurred_at` (NOW() within one transaction) without skipping or
    duplicating.
    """
    bounded_limit = max(1, min(int(limit), 200))

    where_clauses: list[str] = ["organization_id = :org_id"]
    params: dict = {"org_id": str(auth.organization_id), "limit": bounded_limit}
    if since is not None:
        where_clauses.append("occurred_at >= CAST(:since AS DATE)")
        params["since"] = since
    if action is not None:
        # Closed vocabulary — adding a future action requires updating
        # this enum AND every consumer (CLI, frontend hook). Catching
        # an unknown value here forces that conversation.
        if action not in ("quota_set", "quota_reset", "quota_reconcile"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown action {action!r}; allowed: quota_set, quota_reset, quota_reconcile",
            )
        where_clauses.append("action = :action")
        params["action"] = action
    if before is not None:
        # Cursor format: `<occurred_at_iso>:<id>`. The `:` separator is
        # safe because ISO timestamps don't contain raw colons in the
        # delimiter slot. Right-most colon splits cleanly: timestamp
        # before, UUID after.
        if ":" not in before:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Malformed `before` cursor; expected `<occurred_at>:<id>`",
            )
        cursor_ts, cursor_id = before.rsplit(":", 1)
        where_clauses.append("(occurred_at, id) < (CAST(:cursor_ts AS TIMESTAMPTZ), CAST(:cursor_id AS UUID))")
        params["cursor_ts"] = cursor_ts
        params["cursor_id"] = cursor_id

    sql = sa_text(
        f"""
        SELECT id, occurred_at, actor, action, before, after
        FROM codeguard_quota_audit_log
        WHERE {" AND ".join(where_clauses)}
        ORDER BY occurred_at DESC, id DESC
        LIMIT :limit
        """
    )
    rows = (await db.execute(sql, params)).all()

    entries = [
        {
            "id": str(r.id),
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "actor": r.actor,
            "action": r.action,
            "before": r.before,
            "after": r.after,
            # Pre-rendered diff summary slot — kept empty here; the CLI
            # `format_audit` helper does the rendering. UI consumers
            # render their own diff in the audit page component.
            "summary": "",
        }
        for r in rows
    ]
    next_cursor: str | None = None
    if len(entries) == bounded_limit and entries:
        # Cursor present only when the page is full (signals "there
        # might be more"). A short page returns null so the UI knows
        # to stop fetching.
        last = rows[-1]
        next_cursor = f"{last.occurred_at.isoformat()}:{last.id}"

    return ok(
        {
            "organization_id": str(auth.organization_id),
            "limit": bounded_limit,
            "entries": entries,
            "next_cursor": next_cursor,
        }
    )


# ---------- /quota/top-users ---------------------------------------------


@quota_router.get("/quota/top-users")
async def get_codeguard_quota_top_users(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 10,
    breakdown: bool = False,
):
    """Top consumers of the org's monthly token cap, sorted by combined
    spend descending.

    Surfaces `codeguard_user_usage` for the caller's org's CURRENT
    period — the natural follow-on question to "we're at 80% of
    cap": which users on the team pushed us there?

    The composite index `ix_codeguard_user_usage_org_period_input_desc`
    on `(organization_id, period_start, input_tokens DESC)` covers
    the leading prefix; the planner can scan that and rank by
    `input_tokens + output_tokens` without a sort step on the
    dominant "small N, current period" workload. `limit` clamps
    1..50 so the response is bounded even for orgs with many users.

    LEFT JOIN on `users` so a deleted user (CASCADE wipes their
    user_usage row, but the user row goes first) flows through with
    `email=""`. Renders as a placeholder in the UI rather than
    silently disappearing — the spend happened and the attribution
    should survive the user deletion.

    Tenant-scoped: WHERE clause pins to `auth.organization_id`. Read-
    only — no mutations from this surface.

    `breakdown=true` adds a `routes` array to each user, populated
    from `codeguard_user_usage_by_route`. Lets the UI show per-user
    "spent 80k via 3 scans + 200 queries" instead of just totals.
    Costs one additional SQL round-trip (no JOIN — keeps the top-N
    query plan simple); skip-by-default since the banner doesn't
    need it.
    """
    bounded_limit = max(1, min(int(limit), 50))

    rows = (
        await db.execute(
            sa_text(
                """
                SELECT
                    u.user_id,
                    COALESCE(usr.email, '')        AS email,
                    u.input_tokens                 AS input_tokens,
                    u.output_tokens                AS output_tokens,
                    (u.input_tokens + u.output_tokens) AS total_tokens
                FROM codeguard_user_usage u
                LEFT JOIN users usr ON usr.id = u.user_id
                WHERE u.organization_id = :org_id
                  AND u.period_start    = date_trunc('month', NOW())::date
                ORDER BY total_tokens DESC, u.user_id
                LIMIT :limit
                """
            ),
            {"org_id": str(auth.organization_id), "limit": bounded_limit},
        )
    ).all()

    # Per-route breakdown — only fetched when `breakdown=true`. Single
    # SQL round-trip for ALL users in the top-N rather than N+1
    # round-trips: WHERE filters by `user_id IN (...)`. The breakdown
    # index `(org, period, total_tokens DESC)` doesn't help here
    # because we're filtering by user_id; the planner falls back to
    # the PK lookup which is fine for small N.
    breakdown_by_user: dict[str, list[dict]] = {}
    if breakdown and rows:
        user_ids = [str(r.user_id) for r in rows]
        breakdown_rows = (
            await db.execute(
                sa_text(
                    """
                    SELECT user_id, route_key, input_tokens, output_tokens
                    FROM codeguard_user_usage_by_route
                    WHERE organization_id = :org_id
                      AND period_start    = date_trunc('month', NOW())::date
                      AND user_id = ANY(CAST(:user_ids AS UUID[]))
                    ORDER BY user_id, (input_tokens + output_tokens) DESC
                    """
                ),
                {"org_id": str(auth.organization_id), "user_ids": user_ids},
            )
        ).all()
        for br in breakdown_rows:
            breakdown_by_user.setdefault(str(br.user_id), []).append(
                {
                    "route_key": br.route_key,
                    "input_tokens": int(br.input_tokens),
                    "output_tokens": int(br.output_tokens),
                    "total_tokens": int(br.input_tokens) + int(br.output_tokens),
                }
            )

    users_payload = []
    for r in rows:
        user_entry: dict = {
            "user_id": str(r.user_id),
            "email": r.email or "",
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "total_tokens": int(r.total_tokens),
        }
        if breakdown:
            # Always include the key in breakdown mode (even if
            # empty) so the UI can rely on the field's presence
            # rather than a "is breakdown mode active" flag.
            user_entry["routes"] = breakdown_by_user.get(str(r.user_id), [])
        users_payload.append(user_entry)

    return ok(
        {
            "organization_id": str(auth.organization_id),
            "limit": bounded_limit,
            "breakdown": breakdown,
            "users": users_payload,
        }
    )
