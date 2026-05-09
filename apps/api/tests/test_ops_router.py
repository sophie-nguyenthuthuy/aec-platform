"""Tests for the ops router (/healthz, /readyz, /metrics).

Three layers:

  * `/healthz` — pure liveness, no deps. One trivial test.
  * `/readyz` — happy + dual-failure paths via monkeypatched
    AdminSessionFactory and Redis create_pool.
  * `/metrics` — token gating + text-format assertions on the
    canonical gauges. We monkey-patch AdminSessionFactory to feed
    deterministic counts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


# ---------- FakeAsyncSession ----------


class FakeAsyncSession:
    """Same shape as the other tests' fakes — push pre-canned results
    in the order the handler will fetch them."""

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
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.one.return_value = {}
        return r


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


def _build_app() -> FastAPI:
    from routers import ops as ops_router

    app = FastAPI()
    app.include_router(ops_router.router)
    return app


# ---------- /healthz ----------


async def test_healthz_returns_200_no_dependencies():
    """Liveness must work with NO external deps. Pin so a refactor
    that adds an import-time DB call doesn't break the cluster
    liveness probe."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# ---------- /readyz ----------


async def test_readyz_200_when_postgres_and_redis_reachable(fake_db, monkeypatch):
    """Both deps up → 200 with both `ok=True`. Pin the body shape so
    operators triaging an outage can read the response without docs."""
    fake_db.push(MagicMock())  # SELECT 1 result

    @asynccontextmanager
    async def _factory() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    monkeypatch.setattr("routers.ops.AdminSessionFactory", _factory)

    fake_pool = MagicMock()
    fake_pool.ping = AsyncMock(return_value=True)

    async def _create_pool(*_a, **_kw):
        return fake_pool

    # Patch the lazy import target inside the readyz handler.
    import sys
    import types

    arq_conn_mod = types.ModuleType("arq.connections")
    arq_conn_mod.RedisSettings = MagicMock()
    arq_conn_mod.RedisSettings.from_dsn = MagicMock(return_value=object())
    arq_conn_mod.create_pool = _create_pool
    sys.modules["arq.connections"] = arq_conn_mod

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/readyz")
    assert res.status_code == 200
    body = res.json()
    assert body["postgres"]["ok"] is True
    assert body["redis"]["ok"] is True


async def test_readyz_503_when_postgres_down(monkeypatch):
    """Postgres unreachable → 503 with `postgres.ok=false` + the
    error captured. Pin the status code so ALB/k8s removes the
    pod from rotation."""

    class BoomSession:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("connection refused")

        async def commit(self): ...
        async def close(self): ...

    @asynccontextmanager
    async def _boom_factory() -> AsyncIterator[BoomSession]:
        yield BoomSession()

    monkeypatch.setattr("routers.ops.AdminSessionFactory", _boom_factory)

    # Redis stub returns OK so we isolate the postgres failure.
    fake_pool = MagicMock()
    fake_pool.ping = AsyncMock(return_value=True)

    async def _create_pool(*_a, **_kw):
        return fake_pool

    import sys
    import types

    arq_conn_mod = types.ModuleType("arq.connections")
    arq_conn_mod.RedisSettings = MagicMock()
    arq_conn_mod.RedisSettings.from_dsn = MagicMock(return_value=object())
    arq_conn_mod.create_pool = _create_pool
    sys.modules["arq.connections"] = arq_conn_mod

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/readyz")
    assert res.status_code == 503
    body = res.json()
    assert body["postgres"]["ok"] is False
    assert "connection refused" in body["postgres"]["error"]


async def test_readyz_503_when_redis_down(fake_db, monkeypatch):
    """Redis unreachable → 503 even when postgres is fine. Pin so a
    Redis blip pulls the pod from rotation rather than silently
    serving traffic that depends on the cron pool."""
    fake_db.push(MagicMock())

    @asynccontextmanager
    async def _factory() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    monkeypatch.setattr("routers.ops.AdminSessionFactory", _factory)

    async def _boom_create_pool(*_a, **_kw):
        raise RuntimeError("redis timeout")

    import sys
    import types

    arq_conn_mod = types.ModuleType("arq.connections")
    arq_conn_mod.RedisSettings = MagicMock()
    arq_conn_mod.RedisSettings.from_dsn = MagicMock(return_value=object())
    arq_conn_mod.create_pool = _boom_create_pool
    sys.modules["arq.connections"] = arq_conn_mod

    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/readyz")
    assert res.status_code == 503
    body = res.json()
    assert body["postgres"]["ok"] is True
    assert body["redis"]["ok"] is False
    assert "redis timeout" in body["redis"]["error"]


# ---------- /metrics ----------
#
# `/metrics` is registered on `routers.ops` and concatenates the
# in-process `core.metrics.render()` output (counters/histograms) with
# `_build_metrics_text()` (DB-driven gauges over the last 5 minutes).
# Tests below pin both surfaces so a Prometheus scrape contract is
# locked.


async def _metrics_app(
    fake_db: FakeAsyncSession,
    monkeypatch,
    token: str | None = None,
) -> FastAPI:
    """Build the app + monkey-patch AdminSessionFactory + the metrics
    token. Token=None means "open" (dev path).

    Also stubs `_sample_queue_depth` so the Redis-touching path
    doesn't try to talk to a real broker during the test."""
    from core.config import get_settings

    @asynccontextmanager
    async def _factory() -> AsyncIterator[FakeAsyncSession]:
        yield fake_db

    monkeypatch.setattr("routers.ops.AdminSessionFactory", _factory)

    async def _noop_sample() -> None:
        return None

    monkeypatch.setattr("core.metrics._sample_queue_depth", _noop_sample)

    # Bust the @lru_cache on get_settings so the `metrics_token` field
    # is re-read after our env tweak.
    get_settings.cache_clear()
    if token is not None:
        monkeypatch.setenv("AEC_METRICS_TOKEN", token)
    else:
        monkeypatch.delenv("AEC_METRICS_TOKEN", raising=False)
    return _build_app()


def _push_metrics_results(fake_db: FakeAsyncSession) -> None:
    """Pre-canned results matching the handler's query order:
    1. webhook_deliveries by status
    2. webhook outbox lag/pending
    3. api_key_calls by success
    4. search_queries count
    5. audit_events count
    """
    wh_status = MagicMock()
    wh_status.mappings.return_value.all.return_value = [
        {"status": "delivered", "n": 12},
        {"status": "failed", "n": 3},
    ]
    fake_db.push(wh_status)

    lag = MagicMock()
    lag.mappings.return_value.one.return_value = {"age_seconds": 42.5, "pending_count": 7}
    fake_db.push(lag)

    api_calls = MagicMock()
    api_calls.mappings.return_value.all.return_value = [
        {"success": True, "n": 100},
        {"success": False, "n": 5},
    ]
    fake_db.push(api_calls)

    search = MagicMock()
    search.mappings.return_value.one.return_value = {"n": 23}
    fake_db.push(search)

    audit = MagicMock()
    audit.mappings.return_value.one.return_value = {"n": 45}
    fake_db.push(audit)


async def test_metrics_open_when_no_token_configured(fake_db, monkeypatch):
    """Dev path: AEC_METRICS_TOKEN unset → endpoint open. Pin so a
    local Prometheus pointed at localhost:8000 keeps working without
    extra config."""
    app = await _metrics_app(fake_db, monkeypatch, token=None)
    _push_metrics_results(fake_db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "aec_webhook_deliveries_total" in res.text


async def test_metrics_401_when_token_configured_but_missing(fake_db, monkeypatch):
    """Prod path: token configured + no `?token=` → 401. Pin so a
    production accidentally exposing /metrics to the internet doesn't
    leak ops data."""
    from core.config import get_settings

    app = await _metrics_app(fake_db, monkeypatch, token="secret-prod-token")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    assert res.status_code == 401
    get_settings.cache_clear()


async def test_metrics_401_on_wrong_token(fake_db, monkeypatch):
    from core.config import get_settings

    app = await _metrics_app(fake_db, monkeypatch, token="secret-prod-token")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics?token=wrong")
    assert res.status_code == 401
    get_settings.cache_clear()


async def test_metrics_emits_canonical_gauges(fake_db, monkeypatch):
    """Pin the metric names + label shape so a Prometheus scrape
    config / Grafana dashboard built off these names doesn't break
    on a refactor."""
    app = await _metrics_app(fake_db, monkeypatch, token=None)
    _push_metrics_results(fake_db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    assert res.status_code == 200
    body = res.text

    # The five canonical gauges must all appear with their HELP+TYPE
    # comments — pin the contract Prometheus parses on.
    for metric in [
        "aec_webhook_deliveries_total",
        "aec_webhook_outbox_lag_seconds",
        "aec_webhook_outbox_pending",
        "aec_api_key_calls_total",
        "aec_search_queries_total",
        "aec_audit_events_total",
    ]:
        assert f"# HELP {metric}" in body, f"missing HELP for {metric}"
        assert f"# TYPE {metric} gauge" in body, f"missing TYPE for {metric}"

    # Spot-check labelled values.
    assert 'aec_webhook_deliveries_total{status="delivered"} 12' in body
    assert 'aec_webhook_deliveries_total{status="failed"} 3' in body
    # Padded to 0 since we didn't push a "pending" status row.
    assert 'aec_webhook_deliveries_total{status="pending"} 0' in body
    assert 'aec_api_key_calls_total{success="true"} 100' in body
    assert 'aec_api_key_calls_total{success="false"} 5' in body
    assert "aec_search_queries_total 23" in body
    assert "aec_audit_events_total 45" in body
    assert "aec_webhook_outbox_pending 7" in body
    assert "aec_webhook_outbox_lag_seconds 42.5" in body


async def test_metrics_handles_zero_state_cleanly(fake_db, monkeypatch):
    """Brand-new platform with no traffic → all gauges 0, no NaN, no
    division-by-zero. Pin so the dashboard doesn't render "NaN" on
    day 1."""
    app = await _metrics_app(fake_db, monkeypatch, token=None)

    # All queries return empty/zero.
    for _ in range(5):
        r = MagicMock()
        r.mappings.return_value.all.return_value = []
        r.mappings.return_value.one.return_value = {
            "n": 0,
            "age_seconds": None,
            "pending_count": 0,
        }
        fake_db.push(r)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/metrics")
    assert res.status_code == 200
    body = res.text
    # Lag-on-empty defaults to 0.0 (not NaN, not None).
    assert "aec_webhook_outbox_lag_seconds 0" in body
    # All three webhook statuses pad to 0.
    for s in ("pending", "delivered", "failed"):
        assert f'aec_webhook_deliveries_total{{status="{s}"}} 0' in body
