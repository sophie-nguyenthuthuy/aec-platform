"""Router tests for the cross-module admin / ops endpoints.

Mounts only `routers.admin` and stubs `AdminSessionFactory` inside the
router module so we can drive the query results from the test body.
The auth dependency is overridden to grant `admin` role; we verify
that lower roles 403.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


USER_ID = UUID("11111111-1111-1111-1111-111111111111")
ORG_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeAsyncSession:
    def __init__(self) -> None:
        self._results: list[Any] = []
        self.executed_stmts: list[Any] = []

    def push(self, value: Any) -> None:
        self._results.append(value)

    async def execute(self, stmt: Any = None, *_a: Any, **_k: Any) -> Any:
        self.executed_stmts.append(stmt)
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = self._results.pop(0) if self._results else []
        result.scalars.return_value = scalars_mock
        return result


@pytest.fixture
def fake_session() -> FakeAsyncSession:
    return FakeAsyncSession()


def _build_app(monkeypatch, fake_session, *, role: str = "admin") -> FastAPI:
    """One-stop fixture: mount router, stub AdminSessionFactory, override auth."""
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import admin

    class _FactoryStub:
        def __call__(self):
            return self

        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(admin, "AdminSessionFactory", _FactoryStub())

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(admin.router)

    auth_ctx = AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role=role,
        email="ops@example.com",
    )
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


@pytest.fixture
async def admin_client(monkeypatch, fake_session) -> AsyncIterator[AsyncClient]:
    app = _build_app(monkeypatch, fake_session, role="admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _scraper_run_row(**overrides: Any):
    base = dict(
        id=uuid4(),
        slug="hanoi",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        ok=True,
        error=None,
        scraped=120,
        matched=110,
        unmatched=10,
        written=110,
        rule_hits={"CONC_C30": 5, "REBAR_CB500": 12},
        unmatched_sample=["Lao động phổ thông"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- /scraper-runs ----------


async def test_list_scraper_runs_returns_rows(admin_client: AsyncClient, fake_session):
    """Happy path: admin sees the rows verbatim, in DB order."""
    fake_session.push(
        [
            _scraper_run_row(slug="hanoi", scraped=120, unmatched=10),
            _scraper_run_row(slug="hcmc", scraped=80, unmatched=40),
        ]
    )
    res = await admin_client.get("/api/v1/admin/scraper-runs")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert len(body) == 2
    assert body[0]["slug"] == "hanoi"
    assert body[0]["scraped"] == 120
    assert body[0]["rule_hits"]["REBAR_CB500"] == 12
    assert body[1]["slug"] == "hcmc"


async def test_list_scraper_runs_respects_slug_filter(admin_client: AsyncClient, fake_session):
    """The slug query param must reach the SQL WHERE clause."""
    fake_session.push([_scraper_run_row(slug="hanoi")])

    res = await admin_client.get("/api/v1/admin/scraper-runs?slug=hanoi&limit=5")
    assert res.status_code == 200
    # Confirm the query filtered by slug — string-compile the stmt and
    # check the literal `hanoi` made it into the WHERE.
    stmt = fake_session.executed_stmts[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'hanoi'" in compiled


async def test_list_scraper_runs_caps_limit(admin_client: AsyncClient):
    """Limit > 200 must 422 — protect the index from a runaway page."""
    res = await admin_client.get("/api/v1/admin/scraper-runs?limit=10000")
    assert res.status_code == 422


async def test_list_scraper_runs_403_for_non_admin(monkeypatch, fake_session):
    """A regular member must NOT see scraper telemetry — it's cross-tenant data."""
    app = _build_app(monkeypatch, fake_session, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/scraper-runs")
    assert res.status_code == 403


# ---------- Normalizer rules CRUD ----------


class _RulesSession:
    """Richer fake session for the normalizer-rules tests.

    `FakeAsyncSession` only handles `execute().scalars().all()`; the
    rules CRUD also needs `add`, `delete`, `commit`, `refresh`, and
    `execute().scalar_one_or_none()`. We could extend the shared
    fixture, but a per-test class keeps the existing tests' simpler
    queue semantics intact.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self._next_scalar: Any = None
        self._next_list: list[Any] = []

    def queue_scalar(self, value: Any) -> None:
        self._next_scalar = value

    def queue_list(self, value: list[Any]) -> None:
        self._next_list = value

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, *_a, **_k) -> None: ...

    async def execute(self, stmt: Any = None, *_a: Any, **_k: Any) -> Any:
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._next_scalar
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = self._next_list
        result.scalars.return_value = scalars_mock
        return result


def _build_rules_app(monkeypatch, session: _RulesSession, *, role: str = "admin"):
    """Mount only the admin router with the rules-aware session installed."""
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth
    from routers import admin

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(admin, "AdminSessionFactory", _Factory())
    # Skip the real refresh — we don't want the test to hit
    # `_load_db_rules` which would loop back to the same fake session.
    from services.price_scrapers import normalizer

    async def _no_refresh():
        return 0

    monkeypatch.setattr(normalizer, "refresh_db_rules", _no_refresh)

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(admin.router)
    auth_ctx = AuthContext(user_id=USER_ID, organization_id=ORG_ID, role=role, email="ops@example.com")
    app.dependency_overrides[require_auth] = lambda: auth_ctx
    return app


async def test_create_normalizer_rule_persists_row(monkeypatch):
    session = _RulesSession()
    app = _build_rules_app(monkeypatch, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/admin/normalizer-rules",
            json={
                "priority": 50,
                "pattern": r"bê\s*tông.*c30",
                "material_code": "CONC_C30",
                "category": "concrete",
                "canonical_name": "Concrete C30",
                "preferred_units": "m3",
            },
        )
    assert res.status_code == 201, res.text

    from models.core import NormalizerRule

    inserted = [o for o in session.added if isinstance(o, NormalizerRule)]
    assert len(inserted) == 1
    assert inserted[0].material_code == "CONC_C30"
    assert inserted[0].priority == 50
    assert inserted[0].pattern == r"bê\s*tông.*c30"


async def test_create_normalizer_rule_400_on_bad_regex(monkeypatch):
    """Invalid regex must surface as a 400 BEFORE the row is written."""
    session = _RulesSession()
    app = _build_rules_app(monkeypatch, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/admin/normalizer-rules",
            json={
                "pattern": "[unclosed",
                "material_code": "X",
                "canonical_name": "X",
            },
        )
    assert res.status_code == 400
    assert "Invalid regex" in res.json()["errors"][0]["message"]
    assert session.added == []


async def test_create_normalizer_rule_403_for_non_admin(monkeypatch):
    """Members can read rules (eventually) but creating them is admin-only."""
    session = _RulesSession()
    app = _build_rules_app(monkeypatch, session, role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/admin/normalizer-rules",
            json={
                "pattern": "x",
                "material_code": "X",
                "canonical_name": "X",
            },
        )
    assert res.status_code == 403


async def test_update_normalizer_rule_patches_only_provided_fields(monkeypatch):
    """PATCH semantics: omitted fields are unchanged."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from models.core import NormalizerRule

    rule_id = uuid4()
    existing = NormalizerRule(
        id=rule_id,
        priority=50,
        pattern="old",
        material_code="OLD_CODE",
        category="concrete",
        canonical_name="Old",
        preferred_units="m3",
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=None,
    )
    session = _RulesSession()
    session.queue_scalar(existing)
    app = _build_rules_app(monkeypatch, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/admin/normalizer-rules/{rule_id}",
            json={"enabled": False},  # only flipping this flag
        )
    assert res.status_code == 200, res.text
    assert existing.enabled is False
    # Other fields untouched.
    assert existing.pattern == "old"
    assert existing.material_code == "OLD_CODE"


async def test_update_normalizer_rule_404_when_missing(monkeypatch):
    session = _RulesSession()
    session.queue_scalar(None)
    app = _build_rules_app(monkeypatch, session)

    from uuid import uuid4

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.patch(
            f"/api/v1/admin/normalizer-rules/{uuid4()}",
            json={"enabled": False},
        )
    assert res.status_code == 404


async def test_delete_normalizer_rule_removes_row(monkeypatch):
    from datetime import UTC, datetime
    from uuid import uuid4

    from models.core import NormalizerRule

    existing = NormalizerRule(
        id=uuid4(),
        priority=50,
        pattern="x",
        material_code="X",
        category=None,
        canonical_name="X",
        preferred_units="",
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=None,
    )
    session = _RulesSession()
    session.queue_scalar(existing)
    app = _build_rules_app(monkeypatch, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/admin/normalizer-rules/{existing.id}")
    assert res.status_code == 204
    assert existing in session.deleted
