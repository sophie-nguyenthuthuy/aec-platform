"""Webhook subscription 7-day health (cycle T1).

Pinned seams:
  1. The endpoint returns the six fields the list-row badge uses:
     `total_7d`, `delivered_7d`, `failed_7d`, `rate_7d`,
     `last_failure_at`, `p95_attempts`. Pin the field set so a
     refactor that renames any of them silently breaks the badge.
  2. `rate_7d` is None (NOT 0) when there have been zero terminal
     deliveries — the badge renders "—" rather than misleading 0%.
  3. 404 on cross-tenant access — does NOT leak that the row
     exists in another org.
  4. Admin-gated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, AsyncIterator
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from middleware.auth import AuthContext, require_auth


pytestmark = pytest.mark.asyncio


ORG_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
USER_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
SUB_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self._results: list[Any] = []

    def push(self, result: Any) -> None:
        self._results.append(result)

    async def commit(self) -> None: ...
    async def close(self) -> None: ...

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((stmt, params or {}))
        if self._results:
            return self._results.pop(0)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.mappings.return_value.one.return_value = {}
        return r


def _build_app(fake_db: _FakeSession, role: str = "admin") -> FastAPI:
    from db.deps import get_db
    from routers import webhooks as webhooks_router

    app = FastAPI()
    app.include_router(webhooks_router.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="ops@example.com",
    )

    async def _db_override() -> AsyncIterator[_FakeSession]:
        yield fake_db

    app.dependency_overrides[require_auth] = lambda: auth_ctx
    app.dependency_overrides[get_db] = _db_override
    return app


def _scalar_result(sub_or_none: Any) -> Any:
    """Helper: build a result whose `.scalar_one_or_none()` returns
    the supplied value (a fake subscription, or None)."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = sub_or_none
    return r


def _aggregate_result(*, total: int, delivered: int, failed: int, last_failure_at, p95) -> Any:
    """Helper: build a result whose `.mappings().one()` returns the
    aggregate query's row."""
    r = MagicMock()
    r.mappings.return_value.one.return_value = {
        "total_7d": total,
        "delivered_7d": delivered,
        "failed_7d": failed,
        "last_failure_at": last_failure_at,
        "p95_attempts": p95,
    }
    return r


def _fake_subscription() -> Any:
    """Stand-in for a `WebhookSubscription` row — only needs to be
    truthy for the existence check."""
    return MagicMock()


# ---------- Field shape ----------


async def test_health_endpoint_returns_pinned_field_set():
    """Pin the six fields the list-row badge keys off. A refactor
    that renames `rate_7d` → `delivery_rate` would silently break
    the badge — fail this test loudly."""
    db = _FakeSession()
    db.push(_scalar_result(_fake_subscription()))  # ownership check
    db.push(
        _aggregate_result(
            total=100,
            delivered=97,
            failed=3,
            last_failure_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            p95=2.0,
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/webhooks/{SUB_ID}/health")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data.keys()) == {
        "total_7d",
        "delivered_7d",
        "failed_7d",
        "rate_7d",
        "last_failure_at",
        "p95_attempts",
    }
    # 97 / (97 + 3) = 0.97 — pin the math so a refactor doesn't
    # silently switch the denominator to total_7d (which would
    # make pending rows penalise the rate).
    assert data["delivered_7d"] == 97
    assert data["failed_7d"] == 3
    assert abs(data["rate_7d"] - 0.97) < 0.001
    assert data["p95_attempts"] == 2.0
    assert data["last_failure_at"].startswith("2026-05-01")


async def test_health_endpoint_rate_is_none_with_zero_terminal_deliveries():
    """A brand-new subscription (or one that's been quiet for a
    week) has zero terminal deliveries. The rate must be None, NOT
    0 — frontend renders None as "—" rather than misleading 0%."""
    db = _FakeSession()
    db.push(_scalar_result(_fake_subscription()))
    db.push(
        _aggregate_result(
            total=0,
            delivered=0,
            failed=0,
            last_failure_at=None,
            p95=None,
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/webhooks/{SUB_ID}/health")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["rate_7d"] is None  # NOT 0, NOT 0.0
    assert data["total_7d"] == 0
    assert data["last_failure_at"] is None


async def test_health_endpoint_excludes_pending_from_rate_denominator():
    """When pending rows exist (still retrying), they should NOT
    drag the rate down. The denominator is delivered + failed
    (terminal states), not total. Pin via a row count where the
    pending portion is significant."""
    db = _FakeSession()
    db.push(_scalar_result(_fake_subscription()))
    db.push(
        _aggregate_result(
            total=20,  # 12 delivered + 4 failed + 4 pending
            delivered=12,
            failed=4,
            last_failure_at=datetime(2026, 5, 1, tzinfo=UTC),
            p95=1.0,
        )
    )

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/webhooks/{SUB_ID}/health")

    assert res.status_code == 200
    data = res.json()["data"]
    # 12 / (12 + 4) = 0.75. If the denominator were total_7d (20),
    # the rate would be 0.6 — pin the difference.
    assert abs(data["rate_7d"] - 0.75) < 0.001


# ---------- Cross-tenant 404 ----------


async def test_health_endpoint_404s_for_unknown_subscription():
    """Subscription doesn't exist (or belongs to a different org).
    Pin 404, NOT 403 — leaking "exists but you can't see it" tells
    a partner that another tenant has that webhook id."""
    db = _FakeSession()
    db.push(_scalar_result(None))  # ownership check returns None

    app = _build_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/webhooks/{SUB_ID}/health")
    assert res.status_code == 404, res.text


# ---------- RBAC ----------


async def test_health_endpoint_403_for_non_admin():
    """Webhook config is admin-only — the health endpoint exposes
    delivery counts that could leak partner activity. Same gating
    as the rest of the namespace."""
    db = _FakeSession()
    app = _build_app(db, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/webhooks/{SUB_ID}/health")
    assert res.status_code == 403, res.text
