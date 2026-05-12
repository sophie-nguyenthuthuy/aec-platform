"""Router tests for /api/v1/permitflow/*. Same FakeAsyncSession pattern as punchlist."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

# pytest-asyncio is configured in `asyncio_mode = "auto"`, so every async
# test is collected automatically. No module-level mark needed.


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
DOSSIER_ID = UUID("44444444-4444-4444-4444-444444444444")
STAGE_ID = UUID("55555555-5555-5555-5555-555555555555")


def _row(**fields: Any) -> dict[str, Any]:
    return fields


def _mappings_result(rows: list[dict] | None = None, row: dict | None = None) -> MagicMock:
    """Build a result object compatible with .mappings().one() / .first() / .all()."""
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
    """Pops results off a queue in execute() order.

    Tests describe the expected DB shape upfront, then call the route;
    the queue runs out → an assertion fires. Mirrors `_ProgrammableSession`
    in test_punchlist_router.py.
    """

    def __init__(self) -> None:
        self._queue: list[Any] = []
        self.added: list[Any] = []

    def queue(self, result: Any) -> _ProgrammableSession:
        self._queue.append(result)
        return self

    def queue_many(self, results: list[Any]) -> _ProgrammableSession:
        self._queue.extend(results)
        return self

    def add(self, obj: Any) -> None:
        self.added.append(obj)

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

    monkeypatch.setattr("routers.permitflow.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import permitflow as router_mod

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


def _dossier_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=DOSSIER_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        name="Hồ sơ chính — Toà A",
        classification="cap_ii",
        investment_type="domestic",
        status="planning",
        location={},
        land_cert_file_id=None,
        land_parcel_no=None,
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
    )
    base.update(overrides)
    return base


def _stage_row(**overrides: Any) -> dict[str, Any]:
    base = dict(
        id=STAGE_ID,
        organization_id=ORG_ID,
        dossier_id=DOSSIER_ID,
        stage_code="gpxd",
        sequence=4,
        authority="SXD",
        status="in_review",
        legal_basis=["luat_xay_dung_2014_2020", "nghi_dinh_15_2021"],
        target_submit_date=date(2026, 5, 15),
        submitted_date=date(2026, 5, 10),
        decision_date=None,
        decision_number=None,
        decision_file_id=None,
        expiry_date=None,
        notes=None,
        created_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- create_dossier ----------


async def test_create_dossier_seeds_five_stages(patch_session, client):
    # The route fires: INSERT dossier (returns dossier row) + INSERT
    # stages (no return). Queue only the first; the second is a no-op
    # result from the default execute() shape.
    patch_session.queue(_mappings_result(row=_dossier_row()))
    patch_session.queue(MagicMock())  # bulk-insert stages

    resp = await client.post(
        "/api/v1/permitflow/dossiers",
        json={
            "project_id": str(PROJECT_ID),
            "name": "Hồ sơ chính — Toà A",
            "classification": "cap_ii",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["data"]["name"] == "Hồ sơ chính — Toà A"
    assert body["data"]["classification"] == "cap_ii"


# ---------- get_dossier ----------


async def test_get_dossier_returns_404_when_missing(patch_session, client):
    patch_session.queue(_mappings_result())  # first() → None
    resp = await client.get(f"/api/v1/permitflow/dossiers/{DOSSIER_ID}")
    assert resp.status_code == 404


async def test_get_dossier_nests_stages_and_submissions(patch_session, client):
    stage1 = _stage_row(id=uuid4(), stage_code="chu_truong_dau_tu", sequence=1, status="approved")
    stage2 = _stage_row(id=uuid4(), stage_code="quy_hoach_1_500", sequence=2)
    sub_row = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        stage_id=stage1["id"],
        round_number=1,
        submission_type="initial",
        submitted_at=datetime(2026, 5, 1, tzinfo=UTC),
        submitted_by=USER_ID,
        receipt_number="BN-001",
        package_file_ids=[],
        outcome="OK",
        outcome_status="accepted",
        outcome_at=datetime(2026, 5, 3, tzinfo=UTC),
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    patch_session.queue(_mappings_result(row=_dossier_row()))
    patch_session.queue(_mappings_result(rows=[stage1, stage2]))
    patch_session.queue(_mappings_result(rows=[sub_row]))

    resp = await client.get(f"/api/v1/permitflow/dossiers/{DOSSIER_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]["stages"]) == 2
    stage_codes = [s["stage_code"] for s in body["data"]["stages"]]
    assert stage_codes == ["chu_truong_dau_tu", "quy_hoach_1_500"]
    assert len(body["data"]["stages"][0]["submissions"]) == 1
    assert body["data"]["stages"][1]["submissions"] == []


# ---------- transition_stage ----------


async def test_transition_approve_requires_decision_fields(patch_session, client):
    resp = await client.post(
        f"/api/v1/permitflow/stages/{STAGE_ID}/transition",
        json={"to_status": "approved"},
    )
    assert resp.status_code == 422  # pydantic validation fires before the route


async def test_transition_blocks_invalid_status_jump(patch_session, client):
    # `not_started` cannot jump straight to `approved` — only via the
    # submitted → in_review → approved chain.
    patch_session.queue(_mappings_result(row=_stage_row(status="not_started")))
    resp = await client.post(
        f"/api/v1/permitflow/stages/{STAGE_ID}/transition",
        json={
            "to_status": "approved",
            "decision_number": "1234/QĐ",
            "decision_date": "2026-05-10",
        },
    )
    assert resp.status_code == 422
    err = resp.json()["errors"][0]
    assert "invalid_transition" in err["message"] or err["code"] == "422"


async def test_transition_approve_sets_gpxd_expiry_default(patch_session, client):
    """GPXD lapses 12 months after decision date when caller omits expiry."""
    patch_session.queue(_mappings_result(row=_stage_row(status="in_review", stage_code="gpxd")))
    approved_row = _stage_row(
        status="approved",
        stage_code="gpxd",
        decision_date=date(2026, 5, 10),
        decision_number="1234/QĐ-SXD",
        expiry_date=date(2027, 5, 10),
    )
    patch_session.queue(_mappings_result(row=approved_row))
    patch_session.queue(MagicMock())  # unlock-next UPDATE

    resp = await client.post(
        f"/api/v1/permitflow/stages/{STAGE_ID}/transition",
        json={
            "to_status": "approved",
            "decision_number": "1234/QĐ-SXD",
            "decision_date": "2026-05-10",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["expiry_date"] == "2027-05-10"


async def test_transition_to_rfi_is_allowed_from_in_review(patch_session, client):
    patch_session.queue(_mappings_result(row=_stage_row(status="in_review")))
    patch_session.queue(_mappings_result(row=_stage_row(status="rfi")))

    resp = await client.post(
        f"/api/v1/permitflow/stages/{STAGE_ID}/transition",
        json={"to_status": "rfi"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rfi"


# ---------- log_submission ----------


async def test_log_submission_bumps_round_number(patch_session, client):
    patch_session.queue(_mappings_result(row=_stage_row(status="preparing")))
    patch_session.queue(_scalar(2))  # max(round_number) = 2 → new = 3

    new_sub = dict(
        id=uuid4(),
        organization_id=ORG_ID,
        stage_id=STAGE_ID,
        round_number=3,
        submission_type="rfi_response",
        submitted_at=datetime(2026, 5, 12, tzinfo=UTC),
        submitted_by=USER_ID,
        receipt_number="BN-003",
        package_file_ids=[],
        outcome=None,
        outcome_status="pending",
        outcome_at=None,
        created_at=datetime(2026, 5, 12, tzinfo=UTC),
    )
    patch_session.queue(_mappings_result(row=new_sub))
    patch_session.queue(MagicMock())  # stage status bump

    resp = await client.post(
        f"/api/v1/permitflow/stages/{STAGE_ID}/submissions",
        json={
            "submission_type": "rfi_response",
            "submitted_at": "2026-05-12T08:00:00+00:00",
            "receipt_number": "BN-003",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["round_number"] == 3
    assert resp.json()["data"]["submission_type"] == "rfi_response"


# ---------- transition matrix (unit-level) ----------


def test_transition_matrix_terminals_have_no_forward_path():
    from routers.permitflow import TRANSITIONS
    from schemas.permitflow import StageStatus

    assert TRANSITIONS[StageStatus.approved] == set(), "approved must be terminal"
    # rejected / withdrawn / expired re-open via `preparing` only.
    for terminal in (StageStatus.rejected, StageStatus.withdrawn, StageStatus.expired):
        assert TRANSITIONS[terminal] == {StageStatus.preparing}


def test_default_authority_routes_fdi_through_bkhdt():
    from schemas.permitflow import (
        Authority,
        InvestmentType,
        ProjectClassification,
        StageCode,
        default_authority,
    )

    assert (
        default_authority(StageCode.chu_truong_dau_tu, ProjectClassification.cap_ii, InvestmentType.fdi)
        == Authority.BKHDT
    )
    assert (
        default_authority(
            StageCode.chu_truong_dau_tu, ProjectClassification.cap_ii, InvestmentType.domestic
        )
        == Authority.UBND_TINH
    )


def test_default_authority_grade_i_tkcs_goes_to_bxd():
    from schemas.permitflow import (
        Authority,
        InvestmentType,
        ProjectClassification,
        StageCode,
        default_authority,
    )

    assert (
        default_authority(StageCode.tham_dinh_tkcs, ProjectClassification.cap_i, InvestmentType.domestic)
        == Authority.BXD
    )
    assert (
        default_authority(StageCode.tham_dinh_tkcs, ProjectClassification.cap_iii, InvestmentType.domestic)
        == Authority.SXD
    )
