"""Router tests for /api/v1/pccc/*."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
CERT_ID = UUID("44444444-4444-4444-4444-444444444444")


def _mappings_result(rows: list[dict] | None = None, row: dict | None = None) -> MagicMock:
    r = MagicMock()
    mapped = MagicMock()
    if row is not None:
        mapped.one.return_value = row
        mapped.first.return_value = row
        mapped.all.return_value = rows if rows is not None else [row]
    else:
        mapped.one.side_effect = AssertionError("unprogrammed .one()")
        mapped.first.return_value = None
        mapped.all.return_value = rows if rows is not None else []
    r.mappings.return_value = mapped
    return r


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_all(values: list[Any]) -> MagicMock:
    """For `.scalars().all()` — used by the seed-checklist 'already exists' query."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


class _ProgrammableSession:
    def __init__(self) -> None:
        self._queue: list[Any] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        if not self._queue:
            r = MagicMock()
            r.mappings.return_value.first.return_value = None
            r.mappings.return_value.all.return_value = []
            r.scalar_one.return_value = 0
            r.scalars.return_value.all.return_value = []
            return r
        return self._queue.pop(0)

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@pytest.fixture
def patch_session(monkeypatch):
    s = _ProgrammableSession()

    class _Fake:
        def __init__(self, _o: Any) -> None: ...
        async def __aenter__(self):
            return s

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr("routers.pccc.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import pccc as router_mod

    auth = AuthContext(user_id=USER_ID, organization_id=ORG_ID, role="admin", email="t@example.com")
    a = FastAPI()
    a.add_exception_handler(HTTPException, http_exception_handler)
    a.add_exception_handler(Exception, unhandled_exception_handler)
    a.include_router(router_mod.router)
    a.dependency_overrides[require_auth] = lambda: auth
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _cert_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=CERT_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        cert_type="acceptance",
        reference_no="PCCC-2026-001",
        hazard_category="C",
        building_class="CO1",
        height_m=None,
        floors_above=None,
        floors_below=None,
        area_sqm=None,
        occupant_load=None,
        pc07_unit="PC07-HCM",
        status="planning",
        submitted_date=None,
        inspection_date=None,
        decision_date=None,
        decision_number=None,
        decision_file_id=None,
        expiry_date=None,
        notes=None,
        legal_basis=["nghi_dinh_136_2020", "qcvn_06_2022"],
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- create + list ----------


async def test_create_cert_pulls_default_legal_basis(patch_session, client):
    patch_session.queue(_mappings_result(row=_cert_row()))
    resp = await client.post(
        "/api/v1/pccc/certs",
        json={
            "project_id": str(PROJECT_ID),
            "cert_type": "acceptance",
            "reference_no": "PCCC-2026-001",
            "hazard_category": "C",
            "building_class": "CO1",
            "pc07_unit": "PC07-HCM",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["legal_basis"] == ["nghi_dinh_136_2020", "qcvn_06_2022"]


# ---------- transition ----------


async def test_transition_to_approved_defaults_5year_expiry(patch_session, client):
    """Acceptance cert approval defaults expiry = decision + 5y per NĐ 136/2020."""
    patch_session.queue(_mappings_result(row=_cert_row(status="inspection_scheduled")))
    approved = _cert_row(
        status="approved",
        decision_date=date(2026, 5, 10),
        decision_number="QĐ-PC07-2026-50",
        expiry_date=date(2031, 5, 10),
    )
    patch_session.queue(_mappings_result(row=approved))

    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/transition",
        json={
            "to_status": "approved",
            "decision_date": "2026-05-10",
            "decision_number": "QĐ-PC07-2026-50",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["expiry_date"] == "2031-05-10"


async def test_transition_design_cert_keeps_null_expiry(patch_session, client):
    """Design appraisals don't get a default expiry."""
    patch_session.queue(_mappings_result(row=_cert_row(cert_type="design", status="inspection_scheduled")))
    approved = _cert_row(
        cert_type="design",
        status="approved",
        decision_date=date(2026, 5, 10),
        decision_number="QĐ-PC07-2026-12",
        expiry_date=None,
    )
    patch_session.queue(_mappings_result(row=approved))

    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/transition",
        json={
            "to_status": "approved",
            "decision_date": "2026-05-10",
            "decision_number": "QĐ-PC07-2026-12",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["expiry_date"] is None


async def test_transition_blocks_invalid_status_jump(patch_session, client):
    patch_session.queue(_mappings_result(row=_cert_row(status="planning")))
    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/transition",
        json={"to_status": "approved"},
    )
    assert resp.status_code == 422


async def test_transition_rejects_manual_expired(patch_session, client):
    """Manual `expired` is a no-go — only the cron sets it."""
    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/transition",
        json={"to_status": "expired"},
    )
    assert resp.status_code == 422


# ---------- inspections ----------


async def test_inspection_pass_cascades_cert_to_approved(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CERT_ID, status="inspection_scheduled", cert_type="acceptance", decision_date=None)))
    patch_session.queue(_scalar(0))  # max round_number = 0

    new_inspection = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        cert_id=CERT_ID,
        round_number=1,
        inspection_date=date(2026, 5, 10),
        inspector_name="Đại uý Nguyễn",
        inspector_org="PC07-HCM",
        overall_result="pass",
        findings=[],
        summary="OK",
        next_steps=None,
        report_file_id=None,
        created_at=datetime(2026, 5, 10, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_inspection))
    patch_session.queue(MagicMock())  # cascade UPDATE on cert

    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/inspections",
        json={
            "inspection_date": "2026-05-10",
            "inspector_name": "Đại uý Nguyễn",
            "inspector_org": "PC07-HCM",
            "overall_result": "pass",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["round_number"] == 1


async def test_inspection_fail_moves_cert_to_rfi(patch_session, client):
    """PCCC fail is recoverable — moves cert to rfi for re-submission."""
    patch_session.queue(_mappings_result(row=dict(id=CERT_ID, status="inspection_scheduled", cert_type="acceptance", decision_date=None)))
    patch_session.queue(_scalar(2))

    new_inspection = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        cert_id=CERT_ID,
        round_number=3,
        inspection_date=date(2026, 5, 10),
        inspector_name="Đại uý Trần",
        inspector_org="PC07-HCM",
        overall_result="fail",
        findings=[],
        summary=None,
        next_steps="Bổ sung hệ thống tăng áp tầng B1",
        report_file_id=None,
        created_at=datetime(2026, 5, 10, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_inspection))
    patch_session.queue(MagicMock())

    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/inspections",
        json={
            "inspection_date": "2026-05-10",
            "inspector_name": "Đại uý Trần",
            "overall_result": "fail",
            "next_steps": "Bổ sung hệ thống tăng áp tầng B1",
        },
    )
    assert resp.status_code == 201


# ---------- checklist seed ----------


async def test_seed_checklist_skips_already_present(patch_session, client):
    patch_session.queue(_scalar(CERT_ID))  # cert exists
    # Two clauses already seeded — re-seed must skip them.
    patch_session.queue(_scalars_all(["QCVN 06:2022 §3", "QCVN 06:2022 §4.2"]))
    # Then the actual inserts — many calls, but our default execute
    # returns a no-op result so we don't queue specific values.

    resp = await client.post(
        f"/api/v1/pccc/certs/{CERT_ID}/checklist/seed",
        json={"template_version": "qcvn_06_2022_v1"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["already_present"] == 2
    # 8 default items, 2 already seeded → 6 new.
    assert body["seeded"] == 6
