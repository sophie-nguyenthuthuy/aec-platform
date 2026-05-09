"""Cross-module search endpoint.

`POST` (not `GET`) because the request body carries an array of scopes
that doesn't compose well as a query string. Tenant-scoped via
`require_auth` — the per-scope SQL also filters by `organization_id`
for belt-and-suspenders.

Also exposes `GET /api/v1/search/analytics` (admin-only) which reads
the `search_queries` telemetry table and returns the aggregates
rendered on the `/settings/search-analytics` page.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from core.envelope import ok
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role, require_min_role
from schemas.search import SearchRequest, SearchResponse
from services.search import (
    compute_analytics,
    log_search,
)
from services.search import (
    search as search_service,
)

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("")
async def search_endpoint(
    payload: SearchRequest,
    background: BackgroundTasks,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Cross-module hybrid search. Returns matches across the
    requested scopes (or all of them if `scopes` is omitted), ordered
    by RRF score within each scope and recency across scopes.

    Telemetry: schedules a `log_search()` write as a background task so
    the row appears in `search_queries` after the response is sent. We
    deliberately use `BackgroundTasks` (not `asyncio.create_task`) so
    the framework is responsible for awaiting the task — uncaught
    exceptions there get logged instead of vanishing.
    """
    results = await search_service(
        organization_id=auth.organization_id,
        query=payload.query,
        scopes=payload.scopes,
        project_id=payload.project_id,
        limit=payload.limit,
    )
    response = SearchResponse(
        query=payload.query,
        total=len(results),
        results=results,
    )

    # Fire-and-forget telemetry. `log_search` swallows its own errors so
    # this never affects the response, but BackgroundTasks runs it
    # AFTER the response has been streamed — keeping search latency
    # purely within the foreground search call.
    background.add_task(
        log_search,
        organization_id=auth.organization_id,
        user_id=auth.user_id,
        query=payload.query,
        scopes=payload.scopes,
        project_id=payload.project_id,
        results=results,
    )

    return ok(response.model_dump(mode="json"))


@router.get("/analytics")
async def search_analytics_endpoint(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    top_n: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Aggregated search-telemetry view. Admin-only — query strings
    can leak project / client names that members shouldn't see in
    aggregate.

    Returns four breakdowns + a totals tile:
      * `top_queries` — most-run queries with avg result count
      * `no_result_queries` — queries that landed empty (content gaps)
      * `scope_distribution` — which modules win the `top_scope` slot
      * `matched_distribution` — keyword vs vector vs both, summed
        across the per-row `matched_on` chips
    """
    payload = await compute_analytics(
        organization_id=auth.organization_id,
        days=days,
        top_n=top_n,
    )
    return ok(payload)
