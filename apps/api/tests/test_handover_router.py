"""Router-level tests for /api/v1/handover/*.

The handover router uses raw SQL via `TenantAwareSession` — tests patch it
with a recording session whose `execute()` returns pre-programmed results.
ML pipeline entry points (`seed_closeout_items`, `generate_om_manual`,
`extract_warranty_items`) are stubbed via `sys.modules["apps.ml.pipelines.handover"]`.

These are smoke tests — they verify HTTP wiring, auth, validation, envelope
shape, and error paths — not SQL correctness (which needs an integration
test against a real Postgres with RLS).
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime, timezone
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


# ---------- Fakes ----------

class _ProgrammableSession:
    """Async session stub that returns pre-programmed `execute()` results in order."""

    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.executes: list[tuple[str, dict]] = []

    def queue(self, result: Any) -> "_ProgrammableSession":
        self._queue.append(result)
        return self

    async def execute(self, stmt, params=None):
        self.executes.append((str(stmt), params or {}))
        if self._queue:
            return self._queue.pop(0)
        # Default: empty/None result, so routes that don't care keep running
        r = MagicMock()
        r.mappings.return_value.first.return_value = None
        r.mappings.return_value.one.return_value = {}
        r.mappings.return_value.all.return_value = []
        r.scalar_one_or_none.return_value = None
        r.scalar_one.return_value = 0
        return r


def _row(**fields: Any) -> MagicMock:
    """A result whose .mappings().one()/first() yields the dict of fields."""
    r = MagicMock()
    r.mappings.return_value.one.return_value = fields
    r.mappings.return_value.first.return_value = fields
    r.mappings.return_value.all.return_value = [fields]
    return r


def _rows(rows: list[dict]) -> MagicMock:
    r = MagicMock()
    r.mappings.return_value.all.return_value = rows
    r.mappings.return_value.first.return_value = rows[0] if rows else None
    return r


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


# ---------- App fixture ----------

@pytest.fixture
def patch_session(monkeypatch):
    """Replace `routers.handover.TenantAwareSession` with a context manager that
    yields a single `_ProgrammableSession` (shared across the `async with`
    blocks a single request may open — handover sometimes opens more than one).
    """
    session = _ProgrammableSession()

    class _FakeTenantAwareSession:
        def __init__(self, org_id: Any) -> None:
            self._org_id = org_id
        async def __aenter__(self):
            return session
        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("routers.handover.TenantAwareSession", _FakeTenantAwareSession)
    return session


@pytest.fixture
def patch_handover_pipeline(monkeypatch):
    """Stub `apps.ml.pipelines.handover` so the router's lazy imports succeed
    without langchain/LLM dependencies. Returns the stub module so tests can
    reassign the three entry points per-test.
    """
    mod = ModuleType("apps.ml.pipelines.handover")
    mod.seed_closeout_items = AsyncMock(return_value=None)
    mod.generate_om_manual = AsyncMock(return_value=([], []))
    mod.extract_warranty_items = AsyncMock(return_value=[])

    # Ensure parent packages exist in sys.modules — `from apps.ml.pipelines.handover
    # import ...` walks the chain.
    for parent in ("apps", "apps.ml", "apps.ml.pipelines"):
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, ModuleType(parent))
    monkeypatch.setitem(sys.modules, "apps.ml.pipelines.handover", mod)
    return mod


@pytest.fixture
def app(fake_auth, patch_session, patch_handover_pipeline) -> Iterator[FastAPI]:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import require_auth
    from routers import handover as handover_router

    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(handover_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Row factories ----------

def _package_row(**overrides) -> dict:
    base = dict(
        id=uuid4(),
        organization_id=UUID("22222222-2222-2222-2222-222222222222"),
        project_id=PROJECT_ID,
        name="Tower A — Handover",
        status="draft",
        scope_summary={},
        export_file_id=None,
        delivered_at=None,
        created_by=UUID("11111111-1111-1111-1111-111111111111"),
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


def _closeout_item_row(**overrides) -> dict:
    base = dict(
        id=uuid4(),
        package_id=uuid4(),
        category="drawings",
        title="As-built drawings — Architectural",
        description=None,
        required=True,
        status="pending",
        assignee_id=None,
        file_ids=[],
        notes=None,
        sort_order=0,
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


# ============================================================
# Packages
# ============================================================

async def test_create_package_returns_envelope_and_triggers_seed(
    client, patch_session, patch_handover_pipeline
):
    pkg = _package_row()
    patch_session.queue(_row(**pkg))

    r = await client.post(
        "/api/v1/handover/packages",
        json={
            "project_id": str(PROJECT_ID),
            "name": "Tower A — Handover",
            "scope_summary": {"floors": 20},
            "auto_populate": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["data"]["name"] == "Tower A — Handover"
    # auto_populate=True ran the seeder
    patch_handover_pipeline.seed_closeout_items.assert_awaited_once()


async def test_create_package_skips_seed_when_auto_populate_false(
    client, patch_session, patch_handover_pipeline
):
    patch_session.queue(_row(**_package_row()))
    r = await client.post(
        "/api/v1/handover/packages",
        json={
            "project_id": str(PROJECT_ID),
            "name": "No seed pls",
            "auto_populate": False,
        },
    )
    assert r.status_code == 201
    patch_handover_pipeline.seed_closeout_items.assert_not_awaited()


async def test_create_package_rejects_empty_name(client):
    r = await client.post(
        "/api/v1/handover/packages",
        json={"project_id": str(PROJECT_ID), "name": ""},
    )
    assert r.status_code == 422


async def test_list_packages_paginates(client, patch_session):
    rows = [
        {
            **_package_row(name=f"Pkg {i}"),
            "closeout_total": 5,
            "closeout_done": 2,
            "warranty_expiring": 1,
            "open_defects": 0,
        }
        for i in range(3)
    ]
    patch_session.queue(_rows(rows))
    patch_session.queue(_scalar(42))

    r = await client.get("/api/v1/handover/packages", params={"limit": 3, "offset": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["data"]) == 3
    assert body["meta"]["total"] == 42


async def test_get_package_returns_404_when_missing(client, patch_session):
    # First execute returns no package row → 404
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    patch_session.queue(empty)

    r = await client.get(f"/api/v1/handover/packages/{uuid4()}")
    assert r.status_code == 404


async def test_get_package_returns_package_with_closeout_items(client, patch_session):
    pkg = _package_row()
    items = [_closeout_item_row(package_id=pkg["id"]) for _ in range(2)]
    patch_session.queue(_row(**pkg))          # package row
    patch_session.queue(_rows(items))          # closeout items

    r = await client.get(f"/api/v1/handover/packages/{pkg['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["id"] == str(pkg["id"])
    assert len(body["data"]["closeout_items"]) == 2


async def test_update_package_requires_at_least_one_field(client):
    r = await client.patch(
        f"/api/v1/handover/packages/{uuid4()}",
        json={},
    )
    assert r.status_code == 400
    assert "no_fields_to_update" in r.text


async def test_update_package_returns_404_when_missing(client, patch_session):
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    patch_session.queue(empty)
    r = await client.patch(
        f"/api/v1/handover/packages/{uuid4()}",
        json={"name": "renamed"},
    )
    assert r.status_code == 404


# ============================================================
# Closeout items
# ============================================================

async def test_add_closeout_item_404_when_package_missing(client, patch_session):
    # Package lookup returns None
    patch_session.queue(_scalar(None))
    r = await client.post(
        f"/api/v1/handover/packages/{uuid4()}/closeout-items",
        json={"category": "drawings", "title": "As-builts"},
    )
    assert r.status_code == 404
    assert "package_not_found" in r.text


async def test_add_closeout_item_persists_row(client, patch_session):
    pkg_id = uuid4()
    patch_session.queue(_scalar(str(pkg_id)))           # package check
    row = _closeout_item_row(package_id=pkg_id, title="Manuals")
    patch_session.queue(_row(**row))                     # INSERT RETURNING

    r = await client.post(
        f"/api/v1/handover/packages/{pkg_id}/closeout-items",
        json={"category": "manuals", "title": "Manuals"},
    )
    # POST creates a closeout item — `add_closeout_item` returns 201 Created
    assert r.status_code == 201, r.text
    assert r.json()["data"]["title"] == "Manuals"


async def test_update_closeout_item_404_when_missing(client, patch_session):
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    patch_session.queue(empty)
    r = await client.patch(
        f"/api/v1/handover/closeout-items/{uuid4()}",
        json={"status": "done"},
    )
    assert r.status_code == 404


# ============================================================
# As-built drawings
# ============================================================

def _asbuilt_row(**overrides) -> dict:
    base = dict(
        id=uuid4(),
        project_id=PROJECT_ID,
        package_id=None,
        drawing_code="A-101",
        discipline="architecture",
        title="Floor Plan L1",
        current_version=1,
        current_file_id=uuid4(),
        superseded_file_ids=[],
        changelog=[{
            "version": 1,
            "file_id": str(uuid4()),
            "change_note": None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }],
        last_updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


async def test_register_as_built_creates_new_when_none_exists(client, patch_session):
    # existing lookup → None; insert → row
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    patch_session.queue(empty)
    patch_session.queue(_row(**_asbuilt_row()))

    r = await client.post(
        "/api/v1/handover/as-builts",
        json={
            "project_id": str(PROJECT_ID),
            "drawing_code": "A-101",
            "discipline": "architecture",
            "title": "Floor Plan L1",
            "file_id": str(uuid4()),
            "change_note": "initial issue",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["drawing_code"] == "A-101"


async def test_register_as_built_bumps_version_when_existing(client, patch_session):
    existing_file = uuid4()
    existing = {
        **_asbuilt_row(current_version=2, current_file_id=existing_file),
        "superseded_file_ids": [uuid4()],
        "changelog": [],
    }
    patch_session.queue(_row(**existing))          # existing lookup
    patch_session.queue(_row(**_asbuilt_row(current_version=3)))  # UPDATE RETURNING

    new_file = uuid4()
    r = await client.post(
        "/api/v1/handover/as-builts",
        json={
            "project_id": str(PROJECT_ID),
            "drawing_code": "A-101",
            "discipline": "architecture",
            "title": "Floor Plan L1 (rev 3)",
            "file_id": str(new_file),
            "change_note": "door schedule update",
        },
    )
    assert r.status_code == 201, r.text
    # The UPDATE was given version=3 and the old current_file_id moved to superseded
    _sql, params = patch_session.executes[-1]
    assert params["version"] == 3
    assert str(existing_file) in params["superseded"]


async def test_list_as_builts_filters_by_discipline(client, patch_session):
    patch_session.queue(_rows([_asbuilt_row()]))

    r = await client.get(
        f"/api/v1/handover/projects/{PROJECT_ID}/as-builts",
        params={"discipline": "architecture"},
    )
    assert r.status_code == 200
    _sql, params = patch_session.executes[0]
    assert params["discipline"] == "architecture"


# ============================================================
# O&M manual generation
# ============================================================

async def test_generate_om_manual_writes_job_and_rows_on_success(
    client, patch_session, patch_handover_pipeline
):
    from schemas.handover import EquipmentSpec, MaintenanceTask

    eq = EquipmentSpec(tag="AHU-01", name="Air handler", discipline="mep")
    task = MaintenanceTask(equipment_tag="AHU-01", task="replace filter", frequency="quarterly")
    patch_handover_pipeline.generate_om_manual = AsyncMock(return_value=([eq], [task]))

    # ai_jobs INSERT, om_manuals INSERT, then pipeline runs (no DB), then
    # om_manuals UPDATE returning + ai_jobs UPDATE.
    patch_session.queue(MagicMock())  # ai_jobs insert
    patch_session.queue(MagicMock())  # om_manuals insert
    # After pipeline: UPDATE om_manuals RETURNING *
    patch_session.queue(_row(
        id=uuid4(),
        project_id=PROJECT_ID,
        package_id=None,
        title="O&M Manual — mep",
        discipline="mep",
        status="ready",
        equipment=[eq.model_dump(mode="json")],
        maintenance_schedule=[task.model_dump(mode="json")],
        source_file_ids=[],
        pdf_file_id=None,
        ai_job_id=uuid4(),
        generated_at=datetime.now(timezone.utc),
        created_by=UUID("11111111-1111-1111-1111-111111111111"),
    ))
    patch_session.queue(MagicMock())  # ai_jobs UPDATE

    r = await client.post(
        "/api/v1/handover/om-manuals/generate",
        json={
            "project_id": str(PROJECT_ID),
            "discipline": "mep",
            "source_file_ids": [str(uuid4())],
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["data"]["status"] == "ready"
    assert body["data"]["equipment"][0]["tag"] == "AHU-01"
    patch_handover_pipeline.generate_om_manual.assert_awaited_once()


async def test_generate_om_manual_marks_failed_on_pipeline_error(
    client, patch_session, patch_handover_pipeline
):
    patch_handover_pipeline.generate_om_manual = AsyncMock(
        side_effect=RuntimeError("llm timeout")
    )
    patch_session.queue(MagicMock())  # ai_jobs insert
    patch_session.queue(MagicMock())  # om_manuals insert
    patch_session.queue(MagicMock())  # failure UPDATE(s)

    r = await client.post(
        "/api/v1/handover/om-manuals/generate",
        json={
            "project_id": str(PROJECT_ID),
            "discipline": "mep",
            "source_file_ids": [str(uuid4())],
        },
    )
    assert r.status_code == 502
    assert "om_manual_pipeline_failed" in r.text


async def test_generate_om_manual_requires_source_files(client):
    r = await client.post(
        "/api/v1/handover/om-manuals/generate",
        json={
            "project_id": str(PROJECT_ID),
            "discipline": "mep",
            "source_file_ids": [],
        },
    )
    assert r.status_code == 422


# ============================================================
# Warranties
# ============================================================

def _warranty_row(**overrides) -> dict:
    base = dict(
        id=uuid4(),
        project_id=PROJECT_ID,
        package_id=None,
        item_name="AHU-01 5yr warranty",
        category="hvac",
        vendor="Daikin",
        contract_file_id=None,
        warranty_period_months=60,
        start_date=date(2024, 1, 1),
        expiry_date=date(2029, 1, 1),
        coverage="Parts & labor",
        claim_contact={"email": "support@daikin.vn"},
        status="active",
        notes=None,
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


async def test_extract_warranty_surfaces_pipeline_error_as_502(
    client, patch_session, patch_handover_pipeline
):
    patch_handover_pipeline.extract_warranty_items = AsyncMock(
        side_effect=RuntimeError("contract OCR failed")
    )
    r = await client.post(
        "/api/v1/handover/warranties/extract",
        json={
            "project_id": str(PROJECT_ID),
            "contract_file_ids": [str(uuid4())],
        },
    )
    assert r.status_code == 502
    assert "warranty_extraction_failed" in r.text


async def test_create_warranty_returns_envelope(client, patch_session):
    patch_session.queue(_row(**_warranty_row()))
    r = await client.post(
        "/api/v1/handover/warranties",
        json={
            "project_id": str(PROJECT_ID),
            "item_name": "AHU-01 5yr warranty",
            "vendor": "Daikin",
            "warranty_period_months": 60,
            "start_date": "2024-01-01",
            "expiry_date": "2029-01-01",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["item_name"] == "AHU-01 5yr warranty"


async def test_list_warranties_paginates(client, patch_session):
    patch_session.queue(_rows([_warranty_row() for _ in range(2)]))
    patch_session.queue(_scalar(2))
    r = await client.get("/api/v1/handover/warranties")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 2


async def test_list_warranties_expiring_within_30_days_builds_cutoff(
    client, patch_session
):
    patch_session.queue(_rows([]))
    patch_session.queue(_scalar(0))
    r = await client.get(
        "/api/v1/handover/warranties",
        params={"expiring_within_days": 30},
    )
    assert r.status_code == 200
    # The first execute (SELECT rows) was given a `cutoff` param ~= today + 30d
    _sql, params = patch_session.executes[0]
    expected = date.today().replace() + (date(2000, 1, 31) - date(2000, 1, 1))
    assert params["cutoff"] == expected


async def test_update_warranty_requires_field_and_404_on_missing(
    client, patch_session
):
    # No fields
    r = await client.patch(
        f"/api/v1/handover/warranties/{uuid4()}",
        json={},
    )
    assert r.status_code == 400

    # Update with no matching row
    empty = MagicMock()
    empty.mappings.return_value.first.return_value = None
    patch_session.queue(empty)
    r = await client.patch(
        f"/api/v1/handover/warranties/{uuid4()}",
        json={"status": "expired"},
    )
    assert r.status_code == 404


# ============================================================
# Defects
# ============================================================

def _defect_row(**overrides) -> dict:
    base = dict(
        id=uuid4(),
        project_id=PROJECT_ID,
        package_id=None,
        title="Cracked tile in lobby",
        description=None,
        location={"room": "Lobby", "coords": [1.2, 3.4]},
        photo_file_ids=[],
        status="open",
        priority="medium",
        assignee_id=None,
        reported_by=UUID("11111111-1111-1111-1111-111111111111"),
        reported_at=datetime.now(timezone.utc),
        resolved_at=None,
        resolution_notes=None,
    )
    base.update(overrides)
    return base


async def test_create_defect_returns_row(client, patch_session):
    patch_session.queue(_row(**_defect_row()))
    r = await client.post(
        "/api/v1/handover/defects",
        json={
            "project_id": str(PROJECT_ID),
            "title": "Cracked tile in lobby",
            "location": {"room": "Lobby"},
            "priority": "medium",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["status"] == "open"


async def test_list_defects_paginates(client, patch_session):
    patch_session.queue(_rows([_defect_row(), _defect_row()]))
    patch_session.queue(_scalar(2))
    r = await client.get("/api/v1/handover/defects")
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 2


async def test_update_defect_resolved_sets_resolved_at(client, patch_session):
    patch_session.queue(_row(**_defect_row(status="resolved")))
    r = await client.patch(
        f"/api/v1/handover/defects/{uuid4()}",
        json={"status": "resolved", "resolution_notes": "replaced tile"},
    )
    assert r.status_code == 200, r.text
    _sql, params = patch_session.executes[-1]
    # The handler must have added `resolved_at = :resolved_at`
    assert "resolved_at" in _sql
    assert isinstance(params["resolved_at"], datetime)


async def test_update_defect_empty_payload_returns_400(client):
    r = await client.patch(
        f"/api/v1/handover/defects/{uuid4()}",
        json={},
    )
    assert r.status_code == 400


# ============================================================
# Auth boundary
# ============================================================

async def test_no_org_scoped_query_escapes_auth(client, patch_session, fake_auth):
    """Every handler must thread `auth.organization_id` into params."""
    patch_session.queue(_rows([]))
    patch_session.queue(_scalar(0))
    await client.get("/api/v1/handover/packages")

    _sql, params = patch_session.executes[0]
    assert params["org"] == str(fake_auth.organization_id)
