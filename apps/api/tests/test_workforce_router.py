"""Router tests for /api/v1/workforce/* + BHXH math + ATLD cycle helpers."""

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
WORKER_ID = UUID("44444444-4444-4444-4444-444444444444")


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

    monkeypatch.setattr("routers.workforce.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import workforce as router_mod

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


def _worker_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=WORKER_ID,
        organization_id=ORG_ID,
        full_name="Nguyễn Văn A",
        dob=date(1990, 1, 1),
        gender="male",
        id_no="079090123456",
        id_issued_date=None,
        id_issued_place=None,
        phone="0901234567",
        address="HCM",
        trade="mason",
        employment_type="direct",
        employer_org_name=None,
        nationality="VN",
        status="active",
        hire_date=date(2025, 1, 1),
        termination_date=None,
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- Pure helpers ----------


def test_validate_vn_id_9_or_12_digits():
    from schemas.workforce import validate_vn_id

    assert validate_vn_id("079090123456") == "079090123456"  # CCCD 12
    assert validate_vn_id("123456789") == "123456789"  # CMND 9
    assert validate_vn_id(None) is None
    assert validate_vn_id("") is None


def test_validate_vn_id_rejects_bad_lengths():
    import pytest as _p

    from schemas.workforce import validate_vn_id

    for bad in ("12345", "12345678901", "abcdefghij", "1234567890"):
        with _p.raises(ValueError):
            validate_vn_id(bad)


def test_default_valid_until_group3_is_3_years():
    from schemas.workforce import SafetyGroup, default_valid_until

    base = date(2026, 5, 1)
    assert default_valid_until(SafetyGroup.g3, base) == date(2029, 4, 30)
    assert default_valid_until(SafetyGroup.g4, base) == date(2029, 4, 30)


def test_default_valid_until_group1_is_2_years():
    from schemas.workforce import SafetyGroup, default_valid_until

    base = date(2026, 5, 1)
    assert default_valid_until(SafetyGroup.g1, base) == date(2028, 4, 30)
    assert default_valid_until(SafetyGroup.g2, base) == date(2028, 4, 30)


def test_compute_monthly_contribution_full_enrollment():
    from schemas.workforce import compute_monthly_contribution

    # 10,000,000 VND base salary, all funds enrolled.
    out = compute_monthly_contribution(10_000_000)
    assert out["bhxh_employer"] == 1_750_000  # 17.5%
    assert out["bhxh_employee"] == 800_000  # 8%
    assert out["bhyt_employer"] == 300_000  # 3%
    assert out["bhyt_employee"] == 150_000  # 1.5%
    assert out["bhtn_employer"] == 100_000  # 1%
    assert out["bhtn_employee"] == 100_000  # 1%
    assert out["kpcd_employer"] == 200_000  # 2% (always)
    assert out["employer_total"] == 2_350_000
    assert out["employee_total"] == 1_050_000


def test_compute_monthly_contribution_partial_skips_excluded_funds():
    from schemas.workforce import compute_monthly_contribution

    out = compute_monthly_contribution(
        10_000_000, bhxh=True, bhyt=False, bhtn=False
    )
    assert out["bhyt_employer"] == 0
    assert out["bhtn_employer"] == 0
    # BHXH still charged.
    assert out["bhxh_employer"] == 1_750_000
    # KPCĐ always applies regardless of fund toggles.
    assert out["kpcd_employer"] == 200_000


# ---------- create_worker ----------


async def test_create_worker_rejects_bad_id_no(patch_session, client):
    resp = await client.post(
        "/api/v1/workforce/workers",
        json={"full_name": "X", "trade": "mason", "id_no": "abc"},
    )
    assert resp.status_code == 422


async def test_create_worker_happy_path(patch_session, client):
    patch_session.queue(_mappings_result(row=_worker_row()))
    resp = await client.post(
        "/api/v1/workforce/workers",
        json={
            "full_name": "Nguyễn Văn A",
            "trade": "mason",
            "id_no": "079090123456",
            "employment_type": "direct",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["full_name"] == "Nguyễn Văn A"


# ---------- training ----------


async def test_record_training_defaults_valid_until_per_group(patch_session, client):
    patch_session.queue(_scalar(WORKER_ID))
    new_t = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        worker_id=WORKER_ID,
        group="3",
        training_org="Trung tâm ATLĐ",
        training_date=date(2026, 5, 1),
        valid_until=date(2029, 4, 30),
        certificate_no="ATLD-2026-001",
        certificate_file_id=None,
        status="valid",
        notes=None,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_t))

    resp = await client.post(
        f"/api/v1/workforce/workers/{WORKER_ID}/training",
        json={
            "group": "3",
            "training_org": "Trung tâm ATLĐ",
            "training_date": "2026-05-01",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["valid_until"] == "2029-04-30"


# ---------- insurance ----------


async def test_enroll_insurance_supersedes_prior(patch_session, client):
    patch_session.queue(_scalar(WORKER_ID))
    new_row = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        worker_id=WORKER_ID,
        basic_salary_vnd=10_000_000,
        bhxh_enrolled=True,
        bhyt_enrolled=True,
        bhtn_enrolled=True,
        bhxh_no="0102030405",
        enrolled_at=date(2026, 5, 1),
        terminated_at=None,
        status="enrolled",
        superseded_by_id=None,
        notes=None,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_row))
    patch_session.queue(MagicMock())  # UPDATE supersedes prior

    resp = await client.post(
        f"/api/v1/workforce/workers/{WORKER_ID}/insurance",
        json={
            "basic_salary_vnd": 10_000_000,
            "bhxh_no": "0102030405",
            "enrolled_at": "2026-05-01",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "enrolled"


async def test_compute_contribution_uses_active_enrollment(patch_session, client):
    patch_session.queue(
        _mappings_result(
            row=dict(
                basic_salary_vnd=10_000_000,
                bhxh_enrolled=True,
                bhyt_enrolled=True,
                bhtn_enrolled=True,
            )
        )
    )
    resp = await client.get(
        f"/api/v1/workforce/workers/{WORKER_ID}/insurance/contribution"
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["bhxh_employer"] == 1_750_000
    assert body["kpcd_employer"] == 200_000


# ---------- foreign permit ----------


async def test_create_permit_blocks_vn_nationals(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=WORKER_ID, nationality="VN")))
    resp = await client.post(
        f"/api/v1/workforce/workers/{WORKER_ID}/permit",
        json={
            "nationality": "VN",
            "passport_no": "B1234567",
            "job_position": "Site engineer",
        },
    )
    assert resp.status_code == 422


async def test_create_permit_succeeds_for_foreign_worker(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=WORKER_ID, nationality="KR")))
    new_row = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        worker_id=WORKER_ID,
        nationality="KR",
        passport_no="M12345678",
        job_position="MEP supervisor",
        permit_no=None,
        issue_date=None,
        expiry_date=None,
        exemption_type="required",
        status="pending",
        notes=None,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_row))

    resp = await client.post(
        f"/api/v1/workforce/workers/{WORKER_ID}/permit",
        json={
            "nationality": "KR",
            "passport_no": "M12345678",
            "job_position": "MEP supervisor",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["nationality"] == "KR"
