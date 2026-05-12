"""Router tests for /api/v1/bondline/*."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
BOND_ID = UUID("44444444-4444-4444-4444-444444444444")
CLAIM_ID = UUID("55555555-5555-5555-5555-555555555555")


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

    monkeypatch.setattr("routers.bondline.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import bondline as router_mod

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


def _bond_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=BOND_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        bond_type="performance",
        bond_no="VCB-2026-001",
        issuing_bank="VCB",
        bank_branch="VCB HCM",
        beneficiary_name="Chủ đầu tư X",
        beneficiary_mst="0309876543",
        face_amount_vnd=5_000_000_000,
        contract_value_vnd=100_000_000_000,
        coverage_pct=None,
        currency="VND",
        issue_date=date(2026, 5, 1),
        effective_date=None,
        expiry_date=date(2027, 5, 1),
        status="active",
        released_at=None,
        released_reason=None,
        bond_file_id=None,
        contract_no="HD-2026-001",
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- Pydantic validation ----------


async def test_create_bond_rejects_unknown_bank(patch_session, client):
    resp = await client.post(
        "/api/v1/bondline/bonds",
        json={
            "project_id": str(PROJECT_ID),
            "bond_type": "performance",
            "bond_no": "X-001",
            "issuing_bank": "UNKNOWN",
            "beneficiary_name": "X",
            "face_amount_vnd": 1000,
            "issue_date": "2026-05-01",
            "expiry_date": "2027-05-01",
        },
    )
    assert resp.status_code == 422


async def test_create_bond_rejects_expiry_before_issue(patch_session, client):
    resp = await client.post(
        "/api/v1/bondline/bonds",
        json={
            "project_id": str(PROJECT_ID),
            "bond_type": "performance",
            "bond_no": "X-001",
            "issuing_bank": "VCB",
            "beneficiary_name": "X",
            "face_amount_vnd": 1000,
            "issue_date": "2026-05-01",
            "expiry_date": "2026-04-01",
        },
    )
    assert resp.status_code == 422


# ---------- Create ----------


async def test_create_bond_happy_path(patch_session, client):
    patch_session.queue(_mappings_result(row=_bond_row()))
    resp = await client.post(
        "/api/v1/bondline/bonds",
        json={
            "project_id": str(PROJECT_ID),
            "bond_type": "performance",
            "bond_no": "VCB-2026-001",
            "issuing_bank": "VCB",
            "beneficiary_name": "Chủ đầu tư X",
            "face_amount_vnd": 5_000_000_000,
            "contract_value_vnd": 100_000_000_000,
            "issue_date": "2026-05-01",
            "expiry_date": "2027-05-01",
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["status"] == "active"
    assert body["face_amount_vnd"] == 5_000_000_000


# ---------- Release ----------


async def test_release_blocks_non_active(patch_session, client):
    patch_session.queue(_mappings_result())  # WHERE filter no row
    resp = await client.post(
        f"/api/v1/bondline/bonds/{BOND_ID}/release",
        json={"released_at": "2027-04-01", "released_reason": "Bàn giao hoàn thành"},
    )
    assert resp.status_code == 409


async def test_release_succeeds_on_active(patch_session, client):
    patch_session.queue(_mappings_result(row=_bond_row(status="released")))
    resp = await client.post(
        f"/api/v1/bondline/bonds/{BOND_ID}/release",
        json={"released_at": "2027-04-01", "released_reason": "Bàn giao hoàn thành"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "released"


# ---------- Claims ----------


async def test_file_default_call_flips_bond_to_claimed(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=BOND_ID, status="active", face_amount_vnd=5_000_000_000)))
    new_claim = dict(
        id=CLAIM_ID,
        organization_id=ORG_ID,
        bond_id=BOND_ID,
        claim_type="default_call",
        claim_amount_vnd=3_000_000_000,
        status="pending",
        filed_date=date(2026, 11, 1),
        decided_date=None,
        decided_amount_vnd=None,
        reason="Vi phạm hợp đồng",
        decision_note=None,
        evidence_file_id=None,
        created_by=USER_ID,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_claim))
    patch_session.queue(MagicMock())  # UPDATE bonds → claimed

    resp = await client.post(
        f"/api/v1/bondline/bonds/{BOND_ID}/claims",
        json={
            "claim_type": "default_call",
            "claim_amount_vnd": 3_000_000_000,
            "filed_date": "2026-11-01",
            "reason": "Vi phạm hợp đồng",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["claim_type"] == "default_call"


async def test_file_claim_rejects_amount_over_face(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=BOND_ID, status="active", face_amount_vnd=1_000_000_000)))
    resp = await client.post(
        f"/api/v1/bondline/bonds/{BOND_ID}/claims",
        json={
            "claim_type": "default_call",
            "claim_amount_vnd": 5_000_000_000,
            "filed_date": "2026-11-01",
        },
    )
    assert resp.status_code == 422


async def test_file_claim_blocks_when_bond_not_active(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=BOND_ID, status="released", face_amount_vnd=1)))
    resp = await client.post(
        f"/api/v1/bondline/bonds/{BOND_ID}/claims",
        json={
            "claim_type": "default_call",
            "filed_date": "2026-11-01",
        },
    )
    assert resp.status_code == 409


# ---------- Decide claim ----------


async def test_decide_claim_persists_decision(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CLAIM_ID, bond_id_fk=BOND_ID, status="pending")))
    patch_session.queue(
        _mappings_result(
            row=dict(
                id=CLAIM_ID,
                organization_id=ORG_ID,
                bond_id=BOND_ID,
                claim_type="default_call",
                claim_amount_vnd=3_000_000_000,
                status="partial",
                filed_date=date(2026, 11, 1),
                decided_date=date(2026, 11, 15),
                decided_amount_vnd=2_500_000_000,
                reason=None,
                decision_note="Phần kiểm tra hồ sơ chấp nhận 2.5 tỷ",
                evidence_file_id=None,
                created_by=USER_ID,
                created_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
    )
    resp = await client.post(
        f"/api/v1/bondline/claims/{CLAIM_ID}/decide",
        json={
            "status": "partial",
            "decided_date": "2026-11-15",
            "decided_amount_vnd": 2_500_000_000,
            "decision_note": "Phần kiểm tra hồ sơ chấp nhận 2.5 tỷ",
        },
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "partial"
    assert body["decided_amount_vnd"] == 2_500_000_000
