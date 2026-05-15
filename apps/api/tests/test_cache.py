"""Unit tests for core/cache.py.

Tests run without Redis — the helper falls back to compute() when
the pool is unreachable. We patch `_get_pool` directly to simulate
hit/miss/error paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.asyncio


async def test_cache_miss_calls_compute_and_stores():
    """First call: Redis returns None → compute runs → result cached."""
    from core import cache

    pool = MagicMock()
    pool.get = AsyncMock(return_value=None)
    pool.set = AsyncMock()
    compute = AsyncMock(return_value={"hello": "vn"})

    with patch.object(cache, "_get_pool", AsyncMock(return_value=pool)):
        result = await cache.get_or_compute(("test", "k1"), compute, ttl_seconds=42)

    assert result == {"hello": "vn"}
    compute.assert_awaited_once()
    # Cached value was written with the right key + TTL
    pool.set.assert_awaited_once()
    args, kwargs = pool.set.call_args
    assert args[0] == "aec:cache:test:k1"
    assert kwargs.get("ex") == 42


async def test_cache_hit_skips_compute():
    """Subsequent call: Redis returns JSON → compute is NOT invoked."""
    from core import cache

    pool = MagicMock()
    pool.get = AsyncMock(return_value=b'{"cached": true}')
    pool.set = AsyncMock()
    compute = AsyncMock(return_value={"should_not": "run"})

    with patch.object(cache, "_get_pool", AsyncMock(return_value=pool)):
        result = await cache.get_or_compute(("test", "k1"), compute)

    assert result == {"cached": True}
    compute.assert_not_awaited()
    pool.set.assert_not_awaited()


async def test_redis_unavailable_falls_through_to_compute():
    """Pool=None (Redis outage) → compute runs every call, no exception."""
    from core import cache

    compute = AsyncMock(return_value="fresh")
    with patch.object(cache, "_get_pool", AsyncMock(return_value=None)):
        result = await cache.get_or_compute(("test", "k1"), compute)

    assert result == "fresh"
    compute.assert_awaited_once()


async def test_corrupt_cache_value_recomputes():
    """Non-JSON in Redis (corruption / version mismatch) → log + recompute,
    don't crash the request."""
    from core import cache

    pool = MagicMock()
    pool.get = AsyncMock(return_value=b"<not json>")
    pool.set = AsyncMock()
    compute = AsyncMock(return_value={"healed": True})

    with patch.object(cache, "_get_pool", AsyncMock(return_value=pool)):
        result = await cache.get_or_compute(("test", "k1"), compute)

    assert result == {"healed": True}
    compute.assert_awaited_once()
    # And re-cached
    pool.set.assert_awaited_once()


async def test_invalidate_deletes_key():
    from core import cache

    pool = MagicMock()
    pool.delete = AsyncMock()
    with patch.object(cache, "_get_pool", AsyncMock(return_value=pool)):
        await cache.invalidate("user", "u-1", "orgs")
    pool.delete.assert_awaited_once_with("aec:cache:user:u-1:orgs")


async def test_invalidate_is_noop_when_redis_unavailable():
    """Cache miss is fine — invalidate-on-no-redis is also fine."""
    from core import cache

    with patch.object(cache, "_get_pool", AsyncMock(return_value=None)):
        # Must not raise.
        await cache.invalidate("user", "u-1", "orgs")


async def test_invalidate_org_surface_uses_scan():
    """Pattern delete uses SCAN, not KEYS * — bounded + non-blocking."""
    from core import cache

    pool = MagicMock()

    async def fake_scan(match=None, count=None):
        for k in [
            "aec:cache:orgs:o1:projects:abc",
            "aec:cache:orgs:o1:projects:def",
        ]:
            yield k

    pool.scan_iter = fake_scan
    pool.delete = AsyncMock()

    with patch.object(cache, "_get_pool", AsyncMock(return_value=pool)):
        await cache.invalidate_org_surface("o1", "projects")

    assert pool.delete.await_count == 2
