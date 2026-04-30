"""Shared pytest fixtures for API tests.

Tests run against the FastAPI app with `require_auth` and `get_db`
dependency-overridden so we don't need a real Postgres or JWT secret.
The `fake_db` is a minimal async session stub that records `add()` calls
and satisfies `flush()` / `refresh()` / `get()` / `execute()` with
parameterisable return values.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Mirror the production PYTHONPATH (see infra/docker/api.Dockerfile:
# `ENV PYTHONPATH=/app/apps:/app/apps/api:/app/apps/ml`). We add:
#   * `apps/api` and `apps/ml` → bare-package imports (`ml.pipelines.drawbridge`)
#   * the repo root              → apps-prefixed imports (`apps.ml.pipelines...`,
#                                    `apps.api.workers.queue`)
# The queue module's lazy pipeline imports use the `apps.*` form, so both
# resolution styles must work under pytest just like they do in Docker.
_API_ROOT = Path(__file__).resolve().parent.parent
_APPS_ROOT = _API_ROOT.parent
_REPO_ROOT = _APPS_ROOT.parent
_ML_ROOT = _APPS_ROOT / "ml"
for _p in (_ML_ROOT, _API_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Minimal env so config.Settings doesn't try to load a .env in CI.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")


# ---------- Integration lane ----------
#
# Three modules — `test_costpulse_rls.py`, `test_costpulse_pipeline_openai.py`,
# `test_price_scrapers_writer.py` — each carry `pytest.mark.integration`. They
# need a live Postgres (with `aec_app` from migration 0010 + the full
# alembic-applied schema) to exercise RLS, real upserts, and the full
# CostPulse pipeline. Skip rules:
#
#   * Default (no flag): collected but deselected. Nothing runs, nothing
#     prints "skipped" — they don't show up at all.
#   * `--integration`: collected and run. The per-module
#     `skipif COSTPULSE_RLS_DB_URL is None` guard still acts as a runtime
#     safety net; if you forgot the env var, you'll see "skipped" with a
#     clear reason rather than a connection error.
#
# We collect-but-deselect (rather than module-level skip) because
# `pytest --collect-only` should show the same test inventory regardless
# of flag, and CI dashboards count "skipped" as noise.
def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that hit a live Postgres / Redis (see Makefile: `make test-api-integration`).",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        return
    deselected = [it for it in items if it.get_closest_marker("integration")]
    if not deselected:
        return
    remaining = [it for it in items if it not in deselected]
    config.hook.pytest_deselected(items=deselected)
    items[:] = remaining


# ---------- Auth ----------


@pytest.fixture
def fake_auth():
    from middleware.auth import AuthContext

    return AuthContext(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        organization_id=UUID("22222222-2222-2222-2222-222222222222"),
        role="admin",
        email="tester@example.com",
    )


# ---------- Fake DB session ----------


class FakeAsyncSession:
    """In-memory async session stub sufficient for router-level tests.

    - `add(obj)` appends to `added`
    - `flush()` / `commit()` / `refresh()` / `close()` are no-ops
    - `get(Model, id)` / `execute(stmt)` return whatever is pre-programmed
      via `set_get()` / `set_execute_result()`
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self._get_map: dict[tuple[type, Any], Any] = {}
        self._execute_results: list[Any] = []

    def set_get(self, model: type, id_: Any, obj: Any) -> None:
        self._get_map[(model, id_)] = obj

    def set_execute_result(self, result: Any) -> None:
        self._execute_results.append(result)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get(self, model: type, id_: Any) -> Any:
        return self._get_map.get((model, id_))

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        if self._execute_results:
            return self._execute_results.pop(0)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        result.mappings.return_value.all.return_value = []
        return result


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


# ---------- App with overrides ----------


@pytest.fixture
def app(fake_auth, fake_db) -> Iterator[FastAPI]:
    """Build an isolated FastAPI instance that mounts only the codeguard router.

    We intentionally don't import `main.app` here — doing so pulls in every
    sibling router (drawbridge, winwork, etc.) and an unrelated import error
    in any of them would block codeguard test collection.
    """
    from fastapi import HTTPException

    from core.envelope import http_exception_handler, unhandled_exception_handler
    from db.deps import get_db
    from middleware.auth import require_auth
    from routers import codeguard as codeguard_router

    async def _override_db() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    test_app = FastAPI()
    # Register the same envelope-shaping exception handlers that `main.py`
    # installs — otherwise 4xx/5xx responses come back as FastAPI's default
    # `{"detail": "..."}` instead of the `{data, meta, errors}` envelope.
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(codeguard_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    test_app.dependency_overrides[get_db] = _override_db
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- Shared factories ----------


@pytest.fixture
def make_citation():
    from schemas.codeguard import Citation

    def _make(**overrides: Any) -> Citation:
        base = dict(
            regulation_id=uuid4(),
            regulation="QCVN 06:2022/BXD",
            section="3.2.1",
            excerpt="Excerpt of fire safety clause",
            source_url=None,
        )
        base.update(overrides)
        return Citation(**base)

    return _make


@pytest.fixture
def make_query_response(make_citation):
    from schemas.codeguard import QueryResponse

    def _make(**overrides: Any) -> QueryResponse:
        base = dict(
            answer="Hành lang thoát nạn phải có chiều rộng tối thiểu 1.4m.",
            confidence=0.82,
            citations=[make_citation()],
            related_questions=["Chiều rộng cầu thang thoát nạn?"],
        )
        base.update(overrides)
        return QueryResponse(**base)

    return _make


@pytest.fixture
def mock_llm(monkeypatch):
    """Factory that stubs the codeguard LLM entry points.

    Usage:
        mock_llm.query(returns=make_query_response())
        mock_llm.scan(findings=[...], regs=[...])

    Side effect: also stubs `services.codeguard_quotas.check_org_quota` /
    `record_org_usage` to a no-op "unlimited" pass-through. The `/query`
    route now does a quota pre-flight that would otherwise hit the
    fake_db's MagicMock-flavoured execute() and crash on the int compare.
    Tests that specifically exercise quota enforcement use their own
    explicit monkeypatch of `check_org_quota` (see test_codeguard_quotas)
    which overrides this default.
    """
    from services.codeguard_quotas import QuotaCheckResult

    async def _unlimited(_db, _org_id):
        return QuotaCheckResult(over_limit=False, limit_kind="unlimited", used=0, limit=None)

    async def _noop_record(*_a, **_kw):
        return None

    monkeypatch.setattr("services.codeguard_quotas.check_org_quota", _unlimited)
    monkeypatch.setattr("services.codeguard_quotas.record_org_usage", _noop_record)

    installed: dict[str, AsyncMock] = {}

    class _Installer:
        def query(self, *, returns) -> AsyncMock:
            mock = AsyncMock(return_value=returns)
            monkeypatch.setattr("ml.pipelines.codeguard.answer_regulation_query", mock)
            installed["query"] = mock
            return mock

        def scan(self, *, findings, regs) -> AsyncMock:
            mock = AsyncMock(return_value=(findings, regs))
            monkeypatch.setattr("ml.pipelines.codeguard.auto_scan_project", mock)
            installed["scan"] = mock
            return mock

        def checklist(self, *, items) -> AsyncMock:
            mock = AsyncMock(return_value=items)
            monkeypatch.setattr("ml.pipelines.codeguard.generate_permit_checklist", mock)
            installed["checklist"] = mock
            return mock

        @property
        def calls(self) -> dict[str, AsyncMock]:
            return installed

    return _Installer()
