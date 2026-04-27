"""Tests for `GET /api/v1/codeguard/health`.

The health endpoint's value comes from being:
  1. Cheap (no LLM calls, no API key pings — just env presence + a
     trivial Postgres SELECT).
  2. Honest (per-dep status that distinguishes "Anthropic key missing"
     from "Postgres unreachable", because those demand very different
     ops responses).
  3. Stable in shape (so dashboards and Kubernetes readiness probes
     can rely on the JSON without parsing message strings).

These tests pin down the shape contract and the aggregate-status
rules. Each dependency check is monkeypatched at the router-module
level so the suite never actually touches Postgres, ES, or external
API keys.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _ok_pg(latency: int = 5) -> dict:
    return {
        "name": "postgres",
        "status": "ok",
        "latency_ms": latency,
        "message": "halfvec column present",
    }


def _down_pg(message: str = "connection refused") -> dict:
    return {
        "name": "postgres",
        "status": "down",
        "latency_ms": 50,
        "message": message,
    }


def _ok_key(name: str) -> dict:
    return {"name": name, "status": "ok", "latency_ms": 0, "message": f"{name} configured"}


def _down_key(name: str) -> dict:
    return {"name": name, "status": "down", "latency_ms": 0, "message": f"{name} not set"}


def _unavailable_es() -> dict:
    return {
        "name": "elasticsearch",
        "status": "unavailable",
        "latency_ms": 0,
        "message": "ELASTICSEARCH_URL not configured (dense-only mode)",
    }


def _down_es() -> dict:
    return {
        "name": "elasticsearch",
        "status": "down",
        "latency_ms": 80,
        "message": "ConnectionRefusedError",
    }


def _patch_health_checks(
    monkeypatch,
    *,
    pg: dict,
    openai_key: dict,
    anthropic_key: dict,
    es: dict,
) -> None:
    """Stub every dep-check helper at the router module so the route
    aggregator runs against deterministic per-dep results."""
    from routers import codeguard as cg_router

    async def _pg(_db):
        return pg

    def _key_factory(returns):
        def _check(_name, _env_var):
            return returns

        return _check

    async def _es():
        return es

    monkeypatch.setattr(cg_router, "_check_postgres", _pg)

    # `_check_api_key_env` takes (name, env_var) — patch with a
    # multiplexer that returns the right stub by `name` arg.
    def _key_dispatch(name: str, env_var: str) -> dict:
        if name == "openai_key":
            return openai_key
        if name == "anthropic_key":
            return anthropic_key
        raise AssertionError(f"unexpected key check: {name}")

    monkeypatch.setattr(cg_router, "_check_api_key_env", _key_dispatch)
    monkeypatch.setattr(cg_router, "_check_elasticsearch", _es)


# ---------- Aggregate status rules ----------------------------------------


async def test_health_ok_when_every_required_dep_is_ok(client, monkeypatch):
    """Required deps all `ok` + optional ES `unavailable` → overall `ok`.
    `unavailable` is the documented "intentionally off" state for an
    optional dep and must NOT degrade the overall status."""
    _patch_health_checks(
        monkeypatch,
        pg=_ok_pg(),
        openai_key=_ok_key("openai_key"),
        anthropic_key=_ok_key("anthropic_key"),
        es=_unavailable_es(),
    )

    res = await client.get("/api/v1/codeguard/health")
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["status"] == "ok"
    assert body["errors"] is None


async def test_health_degraded_when_optional_dep_down(client, monkeypatch):
    """Required deps `ok` but ES configured-and-unreachable → `degraded`.
    Service can still answer (dense-only retrieval); just with reduced
    capability. Load balancers should keep the pod in rotation but
    surface the warning to ops dashboards."""
    _patch_health_checks(
        monkeypatch,
        pg=_ok_pg(),
        openai_key=_ok_key("openai_key"),
        anthropic_key=_ok_key("anthropic_key"),
        es=_down_es(),
    )

    res = await client.get("/api/v1/codeguard/health")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "degraded"


async def test_health_down_when_postgres_unreachable(client, monkeypatch):
    """Required dep `down` → overall `down`, regardless of optional
    state. Kubernetes readiness probes should pull this pod out of
    rotation; queries against it would fail on every retrieval."""
    _patch_health_checks(
        monkeypatch,
        pg=_down_pg("connection refused"),
        openai_key=_ok_key("openai_key"),
        anthropic_key=_ok_key("anthropic_key"),
        es=_unavailable_es(),
    )

    res = await client.get("/api/v1/codeguard/health")
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["status"] == "down"
    pg = next(d for d in body["data"]["deps"] if d["name"] == "postgres")
    assert pg["status"] == "down"
    assert "connection refused" in pg["message"]


async def test_health_down_when_anthropic_key_missing(client, monkeypatch):
    """Anthropic key is required (no LLM = no Q&A surface). Missing
    key → `down`. Ops triage: distinct from Postgres-down by the per-
    dep message; same overall status."""
    _patch_health_checks(
        monkeypatch,
        pg=_ok_pg(),
        openai_key=_ok_key("openai_key"),
        anthropic_key=_down_key("anthropic_key"),
        es=_unavailable_es(),
    )

    res = await client.get("/api/v1/codeguard/health")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "down"


# ---------- Shape contract ------------------------------------------------


async def test_health_envelope_carries_per_dep_records(client, monkeypatch):
    """The `deps` array carries one entry per dep with the documented
    field shape — pin it so dashboards and OTEL collectors can rely
    on the JSON without runtime introspection."""
    _patch_health_checks(
        monkeypatch,
        pg=_ok_pg(latency=12),
        openai_key=_ok_key("openai_key"),
        anthropic_key=_ok_key("anthropic_key"),
        es=_unavailable_es(),
    )

    res = await client.get("/api/v1/codeguard/health")
    body = res.json()
    deps = body["data"]["deps"]
    assert {d["name"] for d in deps} == {
        "postgres",
        "openai_key",
        "anthropic_key",
        "elasticsearch",
    }
    for d in deps:
        # Every dep entry has all four fields; `latency_ms` is a number,
        # `status` is one of the documented values.
        assert set(d.keys()) >= {"name", "status", "latency_ms", "message"}
        assert d["status"] in {"ok", "down", "unavailable"}
        assert isinstance(d["latency_ms"], int)


async def test_health_does_not_require_auth(app, monkeypatch):
    """The route is reachable without a JWT — Kubernetes liveness probes
    don't carry auth headers, and forcing them would either require a
    static probe token (operational drag) or break the probe entirely.
    """
    from httpx import ASGITransport, AsyncClient

    _patch_health_checks(
        monkeypatch,
        pg=_ok_pg(),
        openai_key=_ok_key("openai_key"),
        anthropic_key=_ok_key("anthropic_key"),
        es=_unavailable_es(),
    )

    # Build a bare client that does NOT ride the test app's
    # require_auth override — proves the route is unauthenticated by
    # design, not just because the test app overrode auth globally.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/codeguard/health")
    assert res.status_code == 200
