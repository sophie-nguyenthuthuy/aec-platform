"""Tests for the CSV/XLSX bulk-import pipeline.

Three layers under test:

  * Pure functions: `parse_upload`, `validate_rows`, the per-entity
    validators. No session, no FastAPI — just bytes in, dicts out.

  * `commit_job`: hands the validated rows to the upsert SQL. We
    inspect the bound params on a `FakeAsyncSession` so the test
    pins the contract: each row is one INSERT ... ON CONFLICT ...
    DO UPDATE call.

  * Router: end-to-end through `POST /api/v1/import/{entity}/preview`
    and `POST /api/v1/import/jobs/{id}/commit`. Verifies the two-phase
    flow + the 400 / 413 / 403 boundary cases.

Idempotency is covered at the SQL-shape layer (the ON CONFLICT clause
is in the bound query), not by re-running a real Postgres — the unique
index lives in migration 0029 and the upsert pattern is the same one
every other module uses.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth  # noqa: F401
from middleware.rbac import Role, require_min_role
from services.imports import (
    MAX_ROWS,
    commit_job,
    parse_upload,
    validate_rows,
)

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("55555555-5555-5555-5555-555555555555")
USER_ID = UUID("66666666-6666-6666-6666-666666666666")


# ---------- FakeAsyncSession ----------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.mappings.return_value.one.return_value = {}
        r.mappings.return_value.one_or_none.return_value = None
        r.mappings.return_value.all.return_value = []
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture(autouse=True)
def patch_tenant_session(fake_db, monkeypatch):
    @asynccontextmanager
    async def _factory(_org_id: UUID) -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    # Both modules open `TenantAwareSession`; patch in both locations.
    monkeypatch.setattr("routers.imports.TenantAwareSession", _factory)
    yield fake_db


# ---------- Parser layer ----------


async def test_parse_csv_normalises_headers_and_skips_blanks():
    """CSV: case-insensitive headers, trimmed cells, blank rows ignored.
    Pin so a refactor that drops `_normalise_header` flips this red."""
    csv_bytes = (
        b"External_ID,Project Name,STATUS\n"
        b"P-1, Toa nha A, planning\n"
        b"\n"  # blank row, must be skipped
        b"P-2,Toa nha B,construction\n"
    )
    rows = parse_upload(content=csv_bytes, filename="projects.csv")
    assert len(rows) == 2
    assert rows[0] == {
        "external_id": "P-1",
        "project_name": "Toa nha A",
        "status": "planning",
    }
    assert rows[1]["external_id"] == "P-2"


async def test_parse_csv_handles_excel_bom():
    """Vietnamese Excel saves CSV with a UTF-8 BOM. utf-8-sig must
    swallow it so the first header doesn't end up as `\\ufeffname`."""
    csv_bytes = "﻿name,external_id\nA,1\n".encode()
    rows = parse_upload(content=csv_bytes, filename="x.csv")
    assert rows[0]["name"] == "A"
    assert rows[0]["external_id"] == "1"


async def test_parse_xlsx_reads_first_sheet():
    """Build a tiny xlsx in-memory via openpyxl, then round-trip it
    through parse_upload. Verifies the openpyxl integration without
    a fixture file on disk."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["external_id", "name", "status"])
    ws.append(["P-1", "Toa nha A", "planning"])
    ws.append(["P-2", "Toa nha B", "design"])
    buf = io.BytesIO()
    wb.save(buf)
    rows = parse_upload(content=buf.getvalue(), filename="projects.xlsx")
    assert len(rows) == 2
    assert rows[0] == {"external_id": "P-1", "name": "Toa nha A", "status": "planning"}


async def test_parse_rejects_unknown_extension():
    """`.txt` / `.json` etc. should fail early with a clear message."""
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_upload(content=b"x", filename="foo.txt")


async def test_parse_rejects_oversized_file():
    """The MAX_ROWS guard kicks in BEFORE the validator runs so a
    user uploading 5000 rows gets a "split it" message, not a 5000-
    item error list."""
    headers = "external_id,name\n"
    body = "\n".join(f"P-{i},x" for i in range(MAX_ROWS + 5))
    with pytest.raises(ValueError, match="cap is"):
        parse_upload(content=(headers + body).encode(), filename="x.csv")


# ---------- Validator layer ----------


async def test_validate_projects_requires_external_id_and_name():
    """Missing `external_id` is fatal — without it we can't upsert
    idempotently. Same for `name` (a project with no name is no use
    in the UI)."""
    valid, errors = validate_rows(
        entity="projects",
        raw_rows=[
            {"external_id": "P-1", "name": "Tower A"},
            {"name": "no-id row"},
            {"external_id": "P-3"},
        ],
    )
    assert len(valid) == 1
    assert valid[0]["external_id"] == "P-1"
    assert len(errors) == 2
    # row_idx is 1-based against the user's spreadsheet (header is row 1).
    assert errors[0]["row_idx"] == 3
    assert "external_id" in errors[0]["message"]
    assert errors[1]["row_idx"] == 4
    assert "name" in errors[1]["message"]


async def test_validate_projects_rejects_unknown_status():
    """`status` must be a canonical lifecycle value — typos like
    "in_progress" should fail loudly rather than silently default."""
    valid, errors = validate_rows(
        entity="projects",
        raw_rows=[{"external_id": "P-1", "name": "x", "status": "in_progress"}],
    )
    assert valid == []
    assert "Invalid status" in errors[0]["message"]


async def test_validate_projects_defaults_status_to_planning():
    """Empty `status` cell → default `planning`. Saves the user from
    adding a column they don't actually care about for greenfield."""
    valid, _ = validate_rows(
        entity="projects",
        raw_rows=[{"external_id": "P-1", "name": "Tower A"}],
    )
    assert valid[0]["status"] == "planning"


async def test_validate_projects_coerces_optional_numerics_softly():
    """Bad `area_sqm` should NOT reject the whole row — losing one
    optional field is better than dropping the project entirely."""
    valid, errors = validate_rows(
        entity="projects",
        raw_rows=[
            {
                "external_id": "P-1",
                "name": "x",
                "area_sqm": "not-a-number",
                "budget_vnd": "5000000000",
                "floors": "12",
            }
        ],
    )
    assert errors == []
    assert valid[0]["area_sqm"] is None
    assert valid[0]["budget_vnd"] == 5_000_000_000
    assert valid[0]["floors"] == 12


async def test_validate_projects_rolls_address_into_jsonb():
    """`city` + `district` get folded into a single JSONB blob the
    upsert can write without a separate join table."""
    valid, _ = validate_rows(
        entity="projects",
        raw_rows=[
            {
                "external_id": "P-1",
                "name": "x",
                "city": "Hà Nội",
                "district": "Cầu Giấy",
            }
        ],
    )
    assert valid[0]["address"] == {"city": "Hà Nội", "district": "Cầu Giấy"}


async def test_validate_suppliers_splits_csv_arrays():
    """`categories` and `provinces` come in as comma-strings from
    spreadsheets; they must arrive at the upsert as Python lists so
    the asyncpg array binding works."""
    valid, _ = validate_rows(
        entity="suppliers",
        raw_rows=[
            {
                "external_id": "S-1",
                "name": "Acme",
                "categories": "cement, steel ,rebar",
                "provinces": "HN, HCM",
                "phone": "+84 123",
                "verified": "yes",
            }
        ],
    )
    row = valid[0]
    assert row["categories"] == ["cement", "steel", "rebar"]
    assert row["provinces"] == ["HN", "HCM"]
    assert row["contact"] == {"phone": "+84 123"}
    assert row["verified"] is True


async def test_validate_rejects_unknown_entity():
    """Defense-in-depth: even if the router sends a bad entity, the
    service must reject it before hitting the SQL helper."""
    with pytest.raises(ValueError, match="Unsupported entity"):
        validate_rows(entity="estimates", raw_rows=[])


# ---------- Commit layer ----------


async def test_commit_projects_issues_one_upsert_per_row(fake_db):
    """Each row → exactly one INSERT ... ON CONFLICT ... DO UPDATE.
    Pinning the contract by counting executes."""
    rows = [
        {"external_id": "P-1", "name": "Tower A", "status": "planning"},
        {"external_id": "P-2", "name": "Tower B", "status": "construction"},
    ]
    written = await commit_job(
        session=fake_db,
        organization_id=ORG_ID,
        entity="projects",
        rows=rows,
    )
    assert written == 2
    assert len(fake_db.calls) == 2
    # ON CONFLICT clause must reference the partial unique index by
    # repeating its predicate — pg infers the index by predicate match.
    sql = str(fake_db.calls[0][0])
    assert "ON CONFLICT (organization_id, external_id)" in sql
    assert "WHERE external_id IS NOT NULL" in sql


async def test_commit_projects_serialises_address_as_json(fake_db):
    """JSONB binding goes through json.dumps + CAST(:x AS JSONB).
    Verify the bound value is a string, not a dict — asyncpg's plain-
    text bind path can't handle dicts directly."""
    await commit_job(
        session=fake_db,
        organization_id=ORG_ID,
        entity="projects",
        rows=[
            {
                "external_id": "P-1",
                "name": "x",
                "address": {"city": "Hà Nội"},
            }
        ],
    )
    params = fake_db.calls[0][1]
    assert isinstance(params["address"], str)
    assert json.loads(params["address"]) == {"city": "Hà Nội"}


async def test_commit_suppliers_uses_pg_array_literal(fake_db):
    """`categories` / `provinces` arrive as Python lists from the
    validator; the upsert binds them as `{a,b,c}` literals through
    `CAST(:x AS TEXT[])`. Quoted to handle commas-inside-values."""
    await commit_job(
        session=fake_db,
        organization_id=ORG_ID,
        entity="suppliers",
        rows=[
            {
                "external_id": "S-1",
                "name": "Acme",
                "categories": ["cement", "steel"],
                "provinces": [],
                "contact": {"phone": "+84"},
                "verified": True,
            }
        ],
    )
    params = fake_db.calls[0][1]
    assert params["categories"] == '{"cement","steel"}'
    assert params["provinces"] == "{}"
    assert json.loads(params["contact"]) == {"phone": "+84"}


async def test_commit_with_empty_rows_is_a_noop(fake_db):
    """No rows → no SQL executes. Lets the router's idempotency
    short-circuit work without hitting the DB."""
    written = await commit_job(
        session=fake_db,
        organization_id=ORG_ID,
        entity="projects",
        rows=[],
    )
    assert written == 0
    assert fake_db.calls == []


# ---------- Router: preview ----------


def _build_app(role: str = "admin") -> FastAPI:
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import imports as imports_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(imports_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="caller@example.com",
    )
    # require_min_role(Role.ADMIN) is a function dependency; override
    # the SAME factory call so the override key matches.
    app.dependency_overrides[require_min_role(Role.ADMIN)] = lambda: auth_ctx
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


async def test_preview_persists_validated_payload(fake_db):
    """E2E preview: parse → validate → INSERT one `import_jobs` row.
    The bound params must reflect the final counts so the analytics
    view doesn't have to re-validate from `rows`."""
    job_id = uuid4()
    from datetime import UTC, datetime

    insert_result = MagicMock()
    insert_result.mappings.return_value.one.return_value = {
        "id": job_id,
        "created_at": datetime(2026, 5, 4, tzinfo=UTC),
    }
    fake_db.push(insert_result)

    csv = b"external_id,name,status\nP-1,Tower A,planning\nP-2,,planning\n"
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/import/projects/preview",
            files={"file": ("projects.csv", csv, "text/csv")},
        )
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["row_count"] == 2
    assert body["valid_count"] == 1
    assert body["error_count"] == 1
    assert body["errors"][0]["row_idx"] == 3  # second data row → spreadsheet row 3
    # Bound params: counts must match.
    params = fake_db.calls[0][1]
    assert params["row_count"] == 2
    assert params["valid_count"] == 1
    assert params["error_count"] == 1
    # JSONB rows blob round-trips.
    rows_blob = json.loads(params["rows"])
    assert rows_blob[0]["external_id"] == "P-1"


async def test_preview_rejects_unknown_entity():
    """`/import/foo/preview` → 422 from the path Literal."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/import/foo/preview",
            files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
        )
    assert res.status_code == 422


async def test_preview_rejects_empty_file():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/import/projects/preview",
            files={"file": ("x.csv", b"", "text/csv")},
        )
    assert res.status_code == 400


async def test_preview_rejects_non_admin():
    """Bulk import is admin-only — members must NOT be able to
    over-write production data via a CSV."""
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from routers import imports as imports_router

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(imports_router.router)
    member_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="member",
        email="m@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: member_ctx

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/import/projects/preview",
            files={"file": ("x.csv", b"name\nA\n", "text/csv")},
        )
    assert res.status_code == 403


# ---------- Router: commit ----------


async def test_commit_runs_upsert_and_stamps_status(fake_db):
    """The committed path: SELECT FOR UPDATE → upserts → UPDATE
    import_jobs to status='committed'. Pin the bound params so the
    state machine stays correct."""
    job_id = uuid4()
    select_result = MagicMock()
    select_result.mappings.return_value.one_or_none.return_value = {
        "id": job_id,
        "entity": "projects",
        "status": "previewed",
        "valid_count": 1,
        "error_count": 0,
        "rows": [{"external_id": "P-1", "name": "Tower A", "status": "planning"}],
        "committed_count": None,
    }
    fake_db.push(select_result)
    # The upsert + the UPDATE return non-mapping results — the fake's
    # default MagicMock is fine.

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/import/jobs/{job_id}/commit")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["status"] == "committed"
    assert body["committed_count"] == 1
    # Calls: SELECT FOR UPDATE, upsert, UPDATE import_jobs.
    assert len(fake_db.calls) == 3
    upsert_sql = str(fake_db.calls[1][0])
    assert "INSERT INTO projects" in upsert_sql
    update_sql = str(fake_db.calls[2][0])
    assert "status = 'committed'" in update_sql


async def test_commit_is_idempotent_on_already_committed_job(fake_db):
    """Re-calling commit on a `committed` row short-circuits — no
    upsert SQL fires. Lets the frontend safely retry on flaky
    networks."""
    job_id = uuid4()
    select_result = MagicMock()
    select_result.mappings.return_value.one_or_none.return_value = {
        "id": job_id,
        "entity": "projects",
        "status": "committed",
        "valid_count": 5,
        "error_count": 0,
        "rows": [],
        "committed_count": 5,
    }
    fake_db.push(select_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/import/jobs/{job_id}/commit")
    assert res.status_code == 200
    assert res.json()["data"]["committed_count"] == 5
    # Only the SELECT — no upsert, no UPDATE.
    assert len(fake_db.calls) == 1


async def test_commit_rejects_job_with_zero_valid_rows(fake_db):
    """A 100%-error preview can't be committed — surface the
    contradiction explicitly instead of silently writing 0 rows."""
    job_id = uuid4()
    select_result = MagicMock()
    select_result.mappings.return_value.one_or_none.return_value = {
        "id": job_id,
        "entity": "projects",
        "status": "previewed",
        "valid_count": 0,
        "error_count": 3,
        "rows": [],
        "committed_count": None,
    }
    fake_db.push(select_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/import/jobs/{job_id}/commit")
    assert res.status_code == 400


async def test_commit_404_on_unknown_job(fake_db):
    """RLS keeps cross-org IDs out of reach — those manifest as 404,
    not 403, since the router can't tell "doesn't exist" from "exists
    in another org" through RLS."""
    select_result = MagicMock()
    select_result.mappings.return_value.one_or_none.return_value = None
    fake_db.push(select_result)

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/import/jobs/{uuid4()}/commit")
    assert res.status_code == 404
