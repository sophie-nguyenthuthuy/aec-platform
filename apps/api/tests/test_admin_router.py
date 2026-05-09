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


# ---------- /scraper-runs/summary ----------


class _MappingsSession:
    """Fake AdminSessionFactory session for the summary endpoint.

    The summary uses raw SQL with `.mappings().all()` (vs the
    `scalars().all()` shape the older tests use). Using a separate
    fake here keeps `FakeAsyncSession` simple — extending it to also
    serve mappings would force every existing test to either set up
    or tolerate a second result queue.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.executed_stmts: list[Any] = []
        self.executed_params: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.executed_stmts.append(stmt)
        self.executed_params.append(dict(params or {}))
        result = MagicMock()
        mappings_mock = MagicMock()
        mappings_mock.all.return_value = self._rows
        result.mappings.return_value = mappings_mock
        return result


def _install_mappings_session(monkeypatch, rows: list[dict[str, Any]]) -> _MappingsSession:
    """Patch AdminSessionFactory to yield the `_MappingsSession` for one test."""
    from routers import admin

    session = _MappingsSession(rows)
    monkeypatch.setattr(admin, "AdminSessionFactory", lambda: session)
    return session


async def test_scraper_runs_summary_returns_per_slug_aggregates(monkeypatch):
    """Happy path: per-slug rows surface verbatim, sorted by drift DESC.

    The fixture data already comes pre-sorted to match the SQL's
    `ORDER BY avg_drift DESC NULLS LAST` so the test only asserts
    pass-through; SQL ordering is exercised in
    `test_scraper_runs_summary_uses_days_param`.
    """
    points_hanoi = [
        {"started_at": "2026-04-01T00:00:00+00:00", "ratio": 0.45},
        {"started_at": "2026-04-02T00:00:00+00:00", "ratio": 0.42},
    ]
    points_hcmc = [
        {"started_at": "2026-04-01T00:00:00+00:00", "ratio": 0.05},
    ]
    rows = [
        {
            "slug": "hanoi",
            "total_runs": 2,
            "failure_rate": 0.0,
            "avg_drift": 0.435,
            "last_run_at": "2026-04-02T00:00:00+00:00",
            "last_run_ok": True,
            "points": points_hanoi,
        },
        {
            "slug": "hcmc",
            "total_runs": 1,
            "failure_rate": 0.0,
            "avg_drift": 0.05,
            "last_run_at": "2026-04-01T00:00:00+00:00",
            "last_run_ok": True,
            "points": points_hcmc,
        },
    ]
    fake = FakeAsyncSession()
    app = _build_app(monkeypatch, fake, role="admin")
    # `_build_app` patches AdminSessionFactory to the scalars-shaped fake;
    # the summary endpoint needs the mappings-shaped one, so reapply.
    _install_mappings_session(monkeypatch, rows)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/scraper-runs/summary?days=14")

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert [r["slug"] for r in body] == ["hanoi", "hcmc"]
    assert body[0]["avg_drift"] == 0.435
    # The sparkline series round-trips through Pydantic's
    # `ScraperRunsSummaryPoint` — ratio nullable for division-by-zero
    # runs, started_at as ISO-8601.
    assert len(body[0]["points"]) == 2
    assert body[0]["points"][0]["ratio"] == 0.45
    assert body[1]["points"][0]["ratio"] == 0.05


async def test_scraper_runs_summary_passes_days_to_sql(monkeypatch):
    """The `days` query param must reach the SQL bindparam.

    Without this, a "show 90 days" tab on the dashboard would silently
    show the default 30. We compare bound values; literal_binds doesn't
    work cleanly on a `text()` query with `make_interval(days := :days)`.
    """
    fake = FakeAsyncSession()
    app = _build_app(monkeypatch, fake, role="admin")
    # Reapply the mappings stub *after* `_build_app` because that helper
    # re-patches `AdminSessionFactory` to its own (scalars-shaped) fake.
    session = _install_mappings_session(monkeypatch, [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/scraper-runs/summary?days=90")
    assert res.status_code == 200, res.text
    assert session.executed_params[0]["days"] == 90


async def test_scraper_runs_summary_403_for_non_admin(monkeypatch):
    """Cross-tenant ops data — members must 403, same as the runs list."""
    fake = FakeAsyncSession()
    app = _build_app(monkeypatch, fake, role="member")
    _install_mappings_session(monkeypatch, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/scraper-runs/summary")
    assert res.status_code == 403


async def test_scraper_runs_summary_validates_days_bounds(monkeypatch):
    """`days` must be 1..365 — protects the index from a runaway scan."""
    fake = FakeAsyncSession()
    app = _build_app(monkeypatch, fake, role="admin")
    _install_mappings_session(monkeypatch, [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/scraper-runs/summary?days=10000")
    assert res.status_code == 422


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


async def test_e2e_create_rule_then_refresh_then_normalise_uses_it(monkeypatch):
    """End-to-end: POST a rule → cache refresh reads the new row →
    `normalise()` sees the rule and routes a matching material to the
    new code.

    This is the integration cousin of the unit-level merge tests in
    `test_price_scrapers.py`. The unit tests pre-populate
    `_db_rules_cache` directly; this one exercises the *real*
    pipeline:

      1. Admin POSTs the rule.
      2. The router commits + invokes `refresh_db_rules()`.
      3. `_load_db_rules()` reads the (just-added) row back via the
         `AdminSessionFactory` it imports.
      4. The cache is populated; a subsequent `normalise()` finds it.

    A regression in any of those four steps — e.g. forgetting the
    cache-bust on POST, or shipping a `_load_db_rules` SQL change
    that drops the `enabled=True` filter — fails this test. The
    pure-unit tests would happily keep passing.
    """
    import re as _re
    from datetime import date
    from decimal import Decimal

    from models.core import NormalizerRule
    from services.price_scrapers import normalizer
    from services.price_scrapers.base import ScrapedPrice

    # A stateful session: `add()` stashes rows; the SELECT issued by
    # `_load_db_rules` returns the in-memory rules that pass the
    # `enabled=True` filter. This is what makes the test E2E vs
    # purely-unit — both write and read paths run.
    #
    # The session also has to soft-handle two unrelated SELECTs the
    # router now triggers as side effects: the audit-emit calls
    # `webhooks.enqueue_event`, which itself queries
    # `webhook_subscriptions`. We discriminate on the SQL text and
    # return an empty list for that one — there are no subscriptions
    # in this test fixture.
    class _StatefulRulesSession:
        def __init__(self) -> None:
            self.rows: list[NormalizerRule] = []
            self.audit_rows: list[Any] = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def add(self, obj):
            # The router populates id + timestamps before add(). We
            # discriminate by type so audit events don't pollute the
            # rules cache when `_load_db_rules` reads back.
            if isinstance(obj, NormalizerRule):
                self.rows.append(obj)
            else:
                # AuditEvent rows go here; tests that care about audit
                # attribution can inspect `session.audit_rows`.
                self.audit_rows.append(obj)

        async def commit(self):
            self.committed = True

        async def refresh(self, *_a, **_k):
            return None

        async def execute(self, stmt=None, *_a, **_k):
            # SQLAlchemy `TextClause` raises on `bool(...)`, so we
            # can't use `stmt or ""`. Stringify defensively.
            sql = str(stmt).lower() if stmt is not None else ""
            result = MagicMock()
            scalars = MagicMock()

            if "webhook_subscriptions" in sql:
                # No subscriptions — `enqueue_event` short-circuits
                # to 0 deliveries and the audit-mirror branch is a no-op.
                scalars.all.return_value = []
            else:
                # Default: serve enabled NormalizerRule rows for the
                # `_load_db_rules` SELECT. The actual rule cache reads
                # from this list after the POST commits.
                scalars.all.return_value = [r for r in self.rows if r.enabled]

            result.scalars.return_value = scalars
            result.scalar_one_or_none.return_value = None
            return result

    session = _StatefulRulesSession()

    from routers import admin as admin_router

    monkeypatch.setattr(admin_router, "AdminSessionFactory", lambda: session)
    # `_load_db_rules` does its own `from db.session import
    # AdminSessionFactory` at call time, so patch the module the
    # normalizer imports too.
    from db import session as db_session

    monkeypatch.setattr(db_session, "AdminSessionFactory", lambda: session)

    # Reset the in-process cache from any prior test bleed-through.
    monkeypatch.setattr(normalizer, "_db_rules_cache", [])

    from fastapi import FastAPI, HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import AuthContext, require_auth

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(admin_router.router)
    app.dependency_overrides[require_auth] = lambda: AuthContext(
        user_id=USER_ID,
        organization_id=ORG_ID,
        role="admin",
        email="ops@example.com",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Step 1: create the rule. The pattern must be more permissive
        # than the existing in-code "C30" rule so we know the DB rule
        # actually overrode it (DB rules sort first in
        # `_get_active_rules`). We point it at a *different* code so
        # the assertion can't be satisfied by the in-code rule firing.
        res = await ac.post(
            "/api/v1/admin/normalizer-rules",
            json={
                "priority": 1,
                "pattern": r"bê\s*tông.*c30",
                "material_code": "CUSTOM_DB_C30",
                "category": "concrete",
                "canonical_name": "Concrete C30 (custom)",
                "preferred_units": "m3",
            },
        )
        assert res.status_code == 201, res.text

    # Sanity: the row landed in the session and the router committed.
    assert session.committed is True
    assert len(session.rows) == 1
    assert session.rows[0].material_code == "CUSTOM_DB_C30"

    # Sanity: the router's POST path called `refresh_db_rules`, which
    # populated `_db_rules_cache` from the (now-stateful) DB.
    assert len(normalizer._db_rules_cache) == 1
    assert normalizer._db_rules_cache[0].code == "CUSTOM_DB_C30"
    # Confirm the regex was compiled correctly server-side — the
    # cache holds a `re.Pattern`, not the raw string.
    assert isinstance(normalizer._db_rules_cache[0].pattern, _re.Pattern)

    # Step 2: run the actual normaliser against a row the new rule
    # should match. If the merge order regressed (e.g. code rules
    # ran first), we'd see CONC_C30 instead.
    rows = [
        ScrapedPrice(
            raw_name="Bê tông thương phẩm C30",
            raw_unit="m3",
            price_vnd=Decimal("2000000"),
            effective_date=date.today(),
            province="Hanoi",
        ),
    ]
    result = normalizer.normalise(rows)
    assert len(result.matched) == 1
    assert result.matched[0].material_code == "CUSTOM_DB_C30"
    assert result.matched[0].name == "Concrete C30 (custom)"


async def test_create_normalizer_rule_emits_audit_event(monkeypatch):
    """Cross-tenant global config edits MUST be audited.

    A platform admin creating/editing a normaliser rule affects every
    tenant's price scrapes; an enterprise security review would
    (rightly) flag silent global-config mutations as a red flag.
    """
    from models.audit import AuditEvent
    from models.core import NormalizerRule

    session = _RulesSession()
    app = _build_rules_app(monkeypatch, session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/admin/normalizer-rules",
            json={
                "priority": 50,
                "pattern": r"bê\s*tông",
                "material_code": "BT",
                "canonical_name": "Bê tông",
            },
        )
    assert res.status_code == 201, res.text

    audit_rows = [o for o in session.added if isinstance(o, AuditEvent)]
    assert len(audit_rows) == 1
    ev = audit_rows[0]
    assert ev.action == "admin.normalizer_rule.create"
    assert ev.organization_id == ORG_ID
    assert ev.actor_user_id == USER_ID
    assert ev.resource_type == "normalizer_rule"
    # The audit `after` mirrors the persisted row's key fields — what
    # we want when reconstructing "who created which rule when."
    assert ev.after["material_code"] == "BT"
    assert ev.after["pattern"] == r"bê\s*tông"

    # Sanity: the rule row itself also landed.
    rules = [o for o in session.added if isinstance(o, NormalizerRule)]
    assert len(rules) == 1


async def test_update_normalizer_rule_emits_audit_event_with_changed_fields_only(monkeypatch):
    """The audit diff captures ONLY the fields that actually changed.

    A no-op PATCH (caller resends the same value) shouldn't pollute
    the audit log; the contract in `services/audit.py` is "minimal
    JSON diffs", and a PATCH with all 7 fields where only one is
    different shouldn't write all 7 into before/after.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from models.audit import AuditEvent
    from models.core import NormalizerRule

    rule_id = uuid4()
    existing = NormalizerRule(
        id=rule_id,
        priority=50,
        pattern="old_pattern",
        material_code="OLD_CODE",
        category="concrete",
        canonical_name="Old name",
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
            json={
                # Same value as existing — should NOT show in diff.
                "priority": 50,
                # Actually changing.
                "enabled": False,
                # Same value as existing — should NOT show in diff.
                "material_code": "OLD_CODE",
            },
        )
    assert res.status_code == 200, res.text

    audit_rows = [o for o in session.added if isinstance(o, AuditEvent)]
    assert len(audit_rows) == 1
    ev = audit_rows[0]
    assert ev.action == "admin.normalizer_rule.update"
    # ONLY the field that actually changed shows up in the diff.
    assert ev.before == {"enabled": True}
    assert ev.after == {"enabled": False}


async def test_update_normalizer_rule_skips_audit_on_noop_patch(monkeypatch):
    """A PATCH where every supplied field equals the existing value
    must not emit an audit row — otherwise re-saving an unchanged
    form pollutes the trail."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from models.audit import AuditEvent
    from models.core import NormalizerRule

    rule_id = uuid4()
    existing = NormalizerRule(
        id=rule_id,
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
        res = await ac.patch(
            f"/api/v1/admin/normalizer-rules/{rule_id}",
            json={"priority": 50, "enabled": True},  # both same as existing
        )
    assert res.status_code == 200
    audit_rows = [o for o in session.added if isinstance(o, AuditEvent)]
    assert audit_rows == []


async def test_delete_normalizer_rule_emits_audit_event_with_before_snapshot(monkeypatch):
    """DELETE must capture the row's contents in `before` BEFORE the
    delete runs — once the row is detached, that snapshot is the only
    record of what existed."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from models.audit import AuditEvent
    from models.core import NormalizerRule

    existing = NormalizerRule(
        id=uuid4(),
        priority=42,
        pattern="some_pattern",
        material_code="DEL_ME",
        category=None,
        canonical_name="Delete me",
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

    audit_rows = [o for o in session.added if isinstance(o, AuditEvent)]
    assert len(audit_rows) == 1
    ev = audit_rows[0]
    assert ev.action == "admin.normalizer_rule.delete"
    assert ev.resource_id == existing.id
    # before mirrors the soon-to-be-deleted row's key fields.
    assert ev.before["material_code"] == "DEL_ME"
    assert ev.before["priority"] == 42


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
