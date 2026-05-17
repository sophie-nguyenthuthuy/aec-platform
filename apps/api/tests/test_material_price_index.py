"""Tests for material_price_index router.

The data set is cross-tenant — these endpoints surface scraped public
data, NOT customer-specific prices. Auth is just to gate anonymous
hammering, not to enforce per-org filtering.

Tests focus on:
  * Auth required (anonymous → 401/403)
  * Query-param wiring (province, category, material code filters
    actually shape the SQL)
  * Series + compare endpoint shapes (per-province grouping for chart
    consumption; pivot table for procurement view)
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import AuthContext, require_auth


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_ctx() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",
        email="estimator@example.com",
    )


def _mock_session(captured: list, *, query_result=None):
    class _R:
        def __init__(self, v):
            self._v = v

        def mappings(self):
            return self

        def scalars(self):
            return self

        def all(self):
            return self._v if isinstance(self._v, list) else []

        def one(self):
            return self._v or {}

    async def fake_execute(stmt, params=None):
        captured.append((str(stmt), dict(params or {})))
        return _R(query_result)

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    return factory


def test_materials_requires_auth(client):
    """Anonymous → 401/403."""
    resp = client.get("/api/v1/material-prices/materials")
    assert resp.status_code in (401, 403)


def test_materials_returns_list(client):
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    captured: list = []
    fake_rows = [
        {
            "material_code": "cement",
            "name": "Xi măng PCB40",
            "category": "binder",
            "unit": "tấn",
            "observation_count": 120,
            "last_observed": date(2026, 5, 1),
            "province_count": 12,
        },
        {
            "material_code": "rebar",
            "name": "Thép cuộn d10",
            "category": "steel",
            "unit": "tấn",
            "observation_count": 200,
            "last_observed": date(2026, 5, 10),
            "province_count": 18,
        },
    ]
    with patch(
        "routers.material_price_index.AdminSessionFactory",
        _mock_session(captured, query_result=fake_rows),
    ):
        resp = client.get("/api/v1/material-prices/materials")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["materials"]) == 2
    assert body["materials"][0]["material_code"] == "cement"
    assert body["materials"][0]["province_count"] == 12
    assert body["materials"][0]["last_observed"] == "2026-05-01"


def test_latest_with_filters_passes_params(client):
    """`province` + `category` filters shape the SQL binds."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    captured: list = []
    with patch(
        "routers.material_price_index.AdminSessionFactory",
        _mock_session(captured, query_result=[]),
    ):
        resp = client.get(
            "/api/v1/material-prices/latest?province=hanoi&category=binder"
        )
    assert resp.status_code == 200
    sql, params = captured[-1]
    assert "province = :province" in sql
    assert "category = :category" in sql
    assert params["province"] == "hanoi"
    assert params["category"] == "binder"


def test_series_groups_by_province(client):
    """Series response groups raw rows by province for chart consumption."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    captured: list = []
    fake_rows = [
        {"province": "hanoi", "effective_date": date(2026, 4, 1), "price_vnd": 1_700_000, "unit": "tấn", "name": "Xi măng PCB40"},
        {"province": "hanoi", "effective_date": date(2026, 5, 1), "price_vnd": 1_750_000, "unit": "tấn", "name": "Xi măng PCB40"},
        {"province": "hcmc", "effective_date": date(2026, 4, 1), "price_vnd": 1_820_000, "unit": "tấn", "name": "Xi măng PCB40"},
        {"province": "hcmc", "effective_date": date(2026, 5, 1), "price_vnd": 1_850_000, "unit": "tấn", "name": "Xi măng PCB40"},
    ]
    with patch(
        "routers.material_price_index.AdminSessionFactory",
        _mock_session(captured, query_result=fake_rows),
    ):
        resp = client.get(
            "/api/v1/material-prices/series?material_code=cement"
        )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["material_code"] == "cement"
    assert body["unit"] == "tấn"
    province_keys = {s["province"] for s in body["series"]}
    assert province_keys == {"hanoi", "hcmc"}
    hanoi_series = next(s for s in body["series"] if s["province"] == "hanoi")
    assert len(hanoi_series["points"]) == 2
    assert hanoi_series["points"][1]["price_vnd"] == 1_750_000


def test_series_requires_material_code(client):
    """`material_code` is required — 422 if missing."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    resp = client.get("/api/v1/material-prices/series")
    assert resp.status_code == 422


def test_series_days_param_bounded(client):
    """days ∈ [30, 730] — defensive."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    resp = client.get(
        "/api/v1/material-prices/series?material_code=cement&days=10"
    )
    assert resp.status_code == 422
    resp2 = client.get(
        "/api/v1/material-prices/series?material_code=cement&days=2000"
    )
    assert resp2.status_code == 422


def test_compare_pivots_correctly(client):
    """Compare endpoint returns a `materials` array, each with a
    `prices` dict keyed by province."""
    app.dependency_overrides[require_auth] = lambda: _auth_ctx()
    captured: list = []

    # First scalar() call returns top-5 provinces, then mappings().all()
    # returns the price rows.
    call_state = {"n": 0}

    async def fake_execute(stmt, params=None):
        sql = str(stmt)
        call_state["n"] += 1

        class _R:
            def scalars(self):
                return self

            def mappings(self):
                return self

            def all(self_inner):
                if "GROUP BY province\n" in sql or "LIMIT 5" in sql:
                    return ["hanoi", "hcmc", "danang", "haiphong", "cantho"]
                # Price rows
                return [
                    {
                        "material_code": "cement",
                        "name": "Xi măng PCB40",
                        "unit": "tấn",
                        "province": "hanoi",
                        "price_vnd": 1_750_000,
                        "effective_date": date(2026, 5, 1),
                    },
                    {
                        "material_code": "cement",
                        "name": "Xi măng PCB40",
                        "unit": "tấn",
                        "province": "hcmc",
                        "price_vnd": 1_850_000,
                        "effective_date": date(2026, 5, 1),
                    },
                    {
                        "material_code": "rebar",
                        "name": "Thép cuộn d10",
                        "unit": "tấn",
                        "province": "hanoi",
                        "price_vnd": 15_200_000,
                        "effective_date": date(2026, 5, 1),
                    },
                ]

        return _R()

    sess = MagicMock()
    sess.execute = AsyncMock(side_effect=fake_execute)

    def factory(*a, **kw):
        class _Ctx:
            async def __aenter__(self_inner):
                return sess

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()

    with patch("routers.material_price_index.AdminSessionFactory", factory):
        resp = client.get("/api/v1/material-prices/compare")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "hanoi" in body["provinces"]
    cement = next(m for m in body["materials"] if m["material_code"] == "cement")
    assert cement["prices"]["hanoi"]["price_vnd"] == 1_750_000
    assert cement["prices"]["hcmc"]["price_vnd"] == 1_850_000
    rebar = next(m for m in body["materials"] if m["material_code"] == "rebar")
    assert rebar["prices"]["hanoi"]["price_vnd"] == 15_200_000
    # HCMC didn't have rebar data — sparse pivot
    assert "hcmc" not in rebar["prices"]
