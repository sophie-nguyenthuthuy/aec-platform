"""Router tests for /api/v1/greenmark/* + scoring helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

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

    monkeypatch.setattr("routers.greenmark.TenantAwareSession", _Fake)
    return s


@pytest.fixture
def app(patch_session) -> FastAPI:
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import greenmark as router_mod

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
        system="lotus_nr",
        target_level="gold",
        achieved_level=None,
        status="planning",
        achieved_points=Decimal("0"),
        max_points=Decimal("0"),
        project_brief={},
        certification_no=None,
        awarded_at=None,
        valid_until=None,
        assessor_name=None,
        notes=None,
        created_by=USER_ID,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return base


# ---------- Pure helpers ----------


def test_score_for_credit_uses_awarded_when_verified():
    from schemas.greenmark import score_for_credit

    verified = score_for_credit(
        {"status": "verified", "claimed_points": Decimal("5"), "awarded_points": Decimal("4")}
    )
    assert verified == Decimal("4")


def test_score_for_credit_uses_claimed_until_verified():
    from schemas.greenmark import score_for_credit

    for status in ("targeted", "documented"):
        v = score_for_credit(
            {"status": status, "claimed_points": Decimal("5"), "awarded_points": Decimal("0")}
        )
        assert v == Decimal("5")


def test_score_for_credit_zero_when_rejected_or_not_attempted():
    from schemas.greenmark import score_for_credit

    for status in ("rejected", "not_attempted"):
        v = score_for_credit(
            {"status": status, "claimed_points": Decimal("5"), "awarded_points": Decimal("3")}
        )
        assert v == Decimal("0")


def test_lotus_level_for_points_at_each_threshold():
    from schemas.greenmark import TargetLevel, lotus_level_for_points

    assert lotus_level_for_points(Decimal("39")) is None
    assert lotus_level_for_points(Decimal("40")) == TargetLevel.certified
    assert lotus_level_for_points(Decimal("55")) == TargetLevel.silver
    assert lotus_level_for_points(Decimal("75")) == TargetLevel.gold
    assert lotus_level_for_points(Decimal("90")) == TargetLevel.platinum
    assert lotus_level_for_points(Decimal("120")) == TargetLevel.platinum


def test_create_validates_level_matches_system():
    """EDGE system + LOTUS gold level should 422 in Pydantic."""
    import pytest as _p
    from pydantic import ValidationError

    from schemas.greenmark import GreenCertificationCreate

    with _p.raises(ValidationError):
        GreenCertificationCreate(
            project_id=PROJECT_ID,
            system="edge",  # type: ignore[arg-type]
            target_level="gold",  # type: ignore[arg-type]
        )


# ---------- create_certification ----------


async def test_create_certification_default_points_zero(patch_session, client):
    patch_session.queue(_mappings_result(row=_cert_row()))
    resp = await client.post(
        "/api/v1/greenmark/certifications",
        json={
            "project_id": str(PROJECT_ID),
            "system": "lotus_nr",
            "target_level": "gold",
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["achieved_points"] == "0"
    assert body["max_points"] == "0"


# ---------- seed_credits ----------


async def test_seed_credits_skips_already_present(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CERT_ID, system="lotus_nr")))  # cert
    patch_session.queue(_scalars_all(["LOTUS-EN-01", "LOTUS-EN-02"]))  # already seeded
    # Then INSERTs + recompute - all default no-op.

    resp = await client.post(
        f"/api/v1/greenmark/certifications/{CERT_ID}/seed-credits",
        json={"template_version": "vgbc_lotus_v3"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    # 11 in NR seed, 2 already present → 9 new.
    assert body["already_present"] == 2
    assert body["seeded"] == 9


async def test_seed_edge_credits_pulls_edge_catalog(patch_session, client):
    """EDGE system selects the EDGE seed list, not LOTUS NR."""
    patch_session.queue(_mappings_result(row=dict(id=CERT_ID, system="edge")))
    patch_session.queue(_scalars_all([]))

    resp = await client.post(
        f"/api/v1/greenmark/certifications/{CERT_ID}/seed-credits",
        json={"template_version": "edge_v1"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["seeded"] == 8  # EDGE seed has 8 items


# ---------- gap_to_next_level ----------


async def test_gap_returns_certified_target_when_below_40(patch_session, client):
    patch_session.queue(
        _mappings_result(row=dict(id=CERT_ID, system="lotus_nr", achieved_points=Decimal("30")))
    )
    patch_session.queue(_mappings_result(rows=[]))

    resp = await client.get(f"/api/v1/greenmark/certifications/{CERT_ID}/gap")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["current_level"] is None
    assert body["next_level"] == "certified"
    assert Decimal(body["points_needed"]) == Decimal("10")


async def test_gap_returns_none_at_platinum(patch_session, client):
    patch_session.queue(
        _mappings_result(row=dict(id=CERT_ID, system="lotus_nr", achieved_points=Decimal("95")))
    )

    resp = await client.get(f"/api/v1/greenmark/certifications/{CERT_ID}/gap")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["current_level"] == "platinum"
    assert body["next_level"] is None


async def test_gap_edge_skips_candidate_credits(patch_session, client):
    """EDGE gap is savings-percentage based — candidate_credits empty."""
    patch_session.queue(
        _mappings_result(row=dict(id=CERT_ID, system="edge", achieved_points=Decimal("0")))
    )

    resp = await client.get(f"/api/v1/greenmark/certifications/{CERT_ID}/gap")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["candidate_credits"] == []


# ---------- score ----------


async def test_score_groups_by_category(patch_session, client):
    patch_session.queue(_mappings_result(row=dict(id=CERT_ID, system="lotus_nr")))
    patch_session.queue(
        _mappings_result(
            rows=[
                dict(category="energy", status="documented", claimed_points=Decimal("12"),
                     awarded_points=Decimal("0"), max_points=Decimal("18")),
                dict(category="energy", status="verified", claimed_points=Decimal("5"),
                     awarded_points=Decimal("4"), max_points=Decimal("5")),
                dict(category="water", status="not_attempted", claimed_points=Decimal("0"),
                     awarded_points=Decimal("0"), max_points=Decimal("8")),
            ]
        )
    )
    patch_session.queue(MagicMock())  # final UPDATE

    resp = await client.post(f"/api/v1/greenmark/certifications/{CERT_ID}/score")
    assert resp.status_code == 200
    body = resp.json()["data"]
    # Earned = 12 (claimed) + 4 (awarded) + 0 = 16
    assert Decimal(body["achieved_points"]) == Decimal("16")
    # Max = 18 + 5 + 8 = 31
    assert Decimal(body["max_points"]) == Decimal("31")
    energy = next(r for r in body["breakdown"] if r["category"] == "energy")
    assert Decimal(energy["earned_points"]) == Decimal("16")
    assert Decimal(energy["max_points"]) == Decimal("23")
