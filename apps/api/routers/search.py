"""Cross-module search endpoint.

`POST` (not `GET`) because the request body carries an array of scopes
that doesn't compose well as a query string. Tenant-scoped via
`require_auth` — the per-scope SQL also filters by `organization_id`
for belt-and-suspenders.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from core.envelope import ok
from middleware.auth import AuthContext, require_auth
from schemas.search import SearchRequest, SearchResponse
from services.search import search as search_service

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("")
async def search_endpoint(
    payload: SearchRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Cross-module keyword search. Returns matches across the
    requested scopes (or all of them if `scopes` is omitted), ordered
    by recency."""
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
    return ok(response.model_dump(mode="json"))
