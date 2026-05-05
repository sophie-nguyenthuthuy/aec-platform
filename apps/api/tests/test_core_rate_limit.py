"""Tests for `core.rate_limit` — the FastAPI dependency limiter on auth /
invitation endpoints.

Distinct from `tests/test_rate_limit.py`, which covers the older
`services.rate_limit` token bucket used by the public RFQ router.

Pins three properties:
  1. The dependency 429s once `limit` requests have been served in `window_sec`.
  2. A Redis outage fails OPEN (logs WARNING, allows the request).
  3. The `key_dep` path keys per-user, so two different users don't share
     a bucket.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def patched_acquire(monkeypatch):
    """Replace the Redis call with an in-memory counter so the test
    doesn't need a live Redis."""
    from core import rate_limit as rl_module

    state: dict[str, int] = {}

    async def _fake_acquire(redis_url: str, key: str, limit: int, window_sec: int) -> bool:
        state[key] = state.get(key, 0) + 1
        return state[key] <= limit

    monkeypatch.setattr(rl_module, "_acquire", _fake_acquire)
    return state


async def test_ip_keyed_limiter_429s_after_limit(patched_acquire):
    from core.rate_limit import rate_limit

    app = FastAPI()
    limiter = rate_limit(prefix="t", limit=3, window_sec=60)

    @app.get("/probe", dependencies=[Depends(limiter)])
    async def _probe():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        codes = [(await ac.get("/probe")).status_code for _ in range(5)]

    assert codes == [200, 200, 200, 429, 429]


async def test_key_dep_separates_buckets(patched_acquire):
    """Two different resolved keys should NOT share a bucket — proves
    user-id keying isolates customers from a single abuser hammering
    the same endpoint."""
    from core.rate_limit import rate_limit

    def _key(user: str = "anon") -> str:
        return user

    app = FastAPI()
    limiter = rate_limit(prefix="u", limit=2, window_sec=60, key_dep=Depends(_key))

    @app.get("/probe", dependencies=[Depends(limiter)])
    async def _probe():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        c1 = (await ac.get("/probe?user=alice")).status_code
        c2 = (await ac.get("/probe?user=alice")).status_code
        c3 = (await ac.get("/probe?user=alice")).status_code
        c4 = (await ac.get("/probe?user=bob")).status_code

    assert (c1, c2, c3, c4) == (200, 200, 429, 200)


@pytest.mark.real_rate_limit
async def test_redis_outage_fails_open(monkeypatch, caplog):
    """When Redis is unreachable, `_acquire` returns True (allow) and
    logs WARNING. Critical: a degraded limiter must not 5xx the api —
    rate limiting is defense-in-depth, not the primary auth gate.

    The `real_rate_limit` marker opts this test out of the autouse
    `_bypass_rate_limit` conftest fixture — we want to exercise the
    actual `_acquire` here, not the always-allow stub."""
    from core import rate_limit as rl_module

    fake_client = MagicMock()
    fake_client.incr = AsyncMock(side_effect=ConnectionError("redis down"))
    fake_client.aclose = AsyncMock()
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda *a, **kw: fake_client,
    )

    with caplog.at_level("WARNING"):
        ok = await rl_module._acquire("redis://nope", "test-key", 5, 60)

    assert ok is True
    assert any("failing open" in r.message.lower() for r in caplog.records), [r.message for r in caplog.records]
