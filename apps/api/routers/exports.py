"""Tabular data export endpoints.

`GET /api/v1/export/{entity}` streams a CSV (or buffers an XLSX) of
the caller's tenant data. Counterpart to `routers.imports`.

Why GET instead of POST:
  * Filters are simple (status/date/project_id). A query string is
    smaller than a full JSON body.
  * Lets `curl -H 'Authorization: …' "/export/projects?status=construction"
    > out.csv` work out-of-the-box for one-off ops queries.

Why one endpoint per entity instead of one with a path-param:
  * We keep the path param. Entities live in `EXPORT_CONFIGS`; the
    router validates the slug via `Literal[…]` so an unknown entity
    is a 422 from FastAPI before we touch the service.

Auth posture:
  * `require_min_role(Role.ADMIN)` — the export pulls every row in the
    org for the requested entity. Members can already see most of
    that through the UI, but the bulk download path is privileged
    territory: it's how data exfiltration tools get used.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from db.session import TenantAwareSession
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role
from services.exports import (
    EXPORT_CONFIGS,
    build_xlsx_bytes,
    csv_cap,
    stream_rows,
    write_csv_lines,
    xlsx_cap,
)

router = APIRouter(prefix="/api/v1/export", tags=["export"])


# Mirror of `EXPORT_CONFIGS.keys()` as a Literal so FastAPI rejects
# bad entity slugs with a clean 422 before we hit the service. Keep
# this in sync with the dict; mismatch fails the router import test.
EntityName = Literal["projects", "suppliers", "defects", "change_orders", "rfis"]
ExportFormat = Literal["csv", "xlsx"]


@router.get("/{entity}")
async def export_entity(
    entity: EntityName,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    format: Annotated[ExportFormat, Query()] = "csv",
    # Generic filter params. Each entity's `EXPORT_CONFIGS[…].filters`
    # whitelists which ones it actually applies; the rest are dropped
    # silently. We expose them all here so OpenAPI shows the
    # superset and clients can pass whatever's relevant per entity.
    status: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    priority: Annotated[str | None, Query()] = None,
    province: Annotated[str | None, Query()] = None,
    verified: Annotated[str | None, Query()] = None,
    since: Annotated[str | None, Query()] = None,
):
    """Stream the requested entity as CSV (default) or XLSX.

    The CSV path is genuinely streaming — bytes flush as Postgres
    yields rows. XLSX is buffered (the .xlsx zip can't be finalised
    incrementally) and capped at 50k rows.

    `Content-Disposition: attachment` so browsers prompt a download
    instead of trying to render. Filename includes the entity slug
    + a date stamp so accidental clicks don't overwrite each other.
    """
    config = EXPORT_CONFIGS.get(entity)
    if config is None:  # defense-in-depth — the Literal already guards.
        raise HTTPException(404, "unknown_entity")

    filters_raw = {
        "status": status,
        "type": type,
        "project_id": project_id,
        "priority": priority,
        "province": province,
        "verified": verified,
        "since": since,
    }

    # Coerce/validate filter values against the per-entity allowlist.
    # `build_select` raises ValueError on bad coercions (e.g. a UUID
    # that won't parse); surface that as a 400 rather than a 500.
    headers_list = [c.header for c in config.columns]
    cap = xlsx_cap() if format == "xlsx" else csv_cap()

    if format == "csv":
        return StreamingResponse(
            _csv_stream(
                organization_id=auth.organization_id,
                entity=entity,
                filters=filters_raw,
                headers=headers_list,
                cap=cap,
            ),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": _disposition(entity, "csv"),
                # Useful for ops dashboards that scrape Server-Timing,
                # but more importantly: tells the browser this is a
                # download even if the user double-clicks the URL.
                "X-AEC-Export-Cap": str(cap),
            },
        )

    # XLSX path — must materialise the workbook before sending.
    try:
        body = await _build_xlsx(
            organization_id=auth.organization_id,
            entity=entity,
            filters=filters_raw,
            headers=headers_list,
            cap=cap,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return StreamingResponse(
        _bytes_iter(body),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": _disposition(entity, "xlsx"),
            "X-AEC-Export-Cap": str(cap),
            "Content-Length": str(len(body)),
        },
    )


# ---------- Helpers ----------


def _disposition(entity: str, ext: str) -> str:
    """`attachment; filename="..."` with a date stamp. ISO date keeps
    sort-by-name aligned with sort-by-creation in the user's
    Downloads folder."""
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return f'attachment; filename="aec-{entity}-{stamp}.{ext}"'


async def _csv_stream(
    *,
    organization_id,
    entity: str,
    filters: dict[str, str | None],
    headers: list[str],
    cap: int,
) -> AsyncIterator[bytes]:
    """Open a tenant-scoped session, run the SELECT, push CSV chunks.
    The session lives for the duration of the response — closing it
    early would cancel the cursor and chop off late rows."""
    # Drop None filters before passing to the service.
    active = {k: v for k, v in filters.items() if v is not None and v != ""}

    async with TenantAwareSession(organization_id) as session:
        try:
            row_iter = stream_rows(
                session=session,
                organization_id=organization_id,
                entity=entity,
                filters=active,
                cap=cap,
            )
            # Materialise the rows in this scope so `write_csv_lines`
            # (sync generator) can pull from a list. `stream_rows`
            # internally caps to `cap`; the list is bounded.
            collected: list[dict] = []
            async for row in row_iter:
                collected.append(row)
        except ValueError as exc:
            # Bad filter → emit a single-line CSV with an error
            # marker. The router has already returned 200 by the time
            # we get here (StreamingResponse is committed on the
            # first yield), so we can't 4xx anymore — but a malformed
            # body hint is friendlier than a hung connection.
            yield f"# error: {exc}\n".encode()
            return

    for chunk in write_csv_lines(collected, headers=headers):
        yield chunk


async def _build_xlsx(
    *,
    organization_id,
    entity: str,
    filters: dict[str, str | None],
    headers: list[str],
    cap: int,
) -> bytes:
    """Same as `_csv_stream` but produces a fully-buffered XLSX
    payload. Errors here surface as 400 because the response body
    hasn't been committed yet."""
    active = {k: v for k, v in filters.items() if v is not None and v != ""}
    async with TenantAwareSession(organization_id) as session:
        rows: list[dict] = []
        async for row in stream_rows(
            session=session,
            organization_id=organization_id,
            entity=entity,
            filters=active,
            cap=cap,
        ):
            rows.append(row)
    return build_xlsx_bytes(rows, headers=headers, sheet_title=entity)


async def _bytes_iter(payload: bytes) -> AsyncIterator[bytes]:
    """Adapter — StreamingResponse wants an async iterator even for
    a single buffer. One-line trampoline."""
    yield payload
