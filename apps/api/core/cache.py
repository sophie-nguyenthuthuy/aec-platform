"""Redis-backed read cache for hot endpoints.

Used by:
  * `/api/v1/me/orgs` — read on every dashboard render. Hot.
  * `/api/v1/projects` list — read on every navigation between modules.
  * `/api/v1/billing/current` — read on every settings page hit.
  * `/api/v1/my-work/summary` — KPI tiles, refetched every 60s on the
    client; cache shaves the DB hop.

Design choices:

  * Cache keys are scoped by `organization_id` + a logical surface
    name + a payload hash. We never share a cache value across orgs.
  * Default TTL is short (30-60s). The dashboard's freshness budget
    is "this minute"; we don't need 5-minute caching.
  * Writes bust the cache on the affected surface. Cache invalidation
    is by prefix-match — every write helper accepts an `org_id` +
    surfaces it knows it touched (vd. project create busts
    `orgs:{id}:projects:*`).
  * Fail-open: a Redis outage produces a cache MISS, not a 500. Callers
    fall through to the DB.

Not used for:
  * Per-user reads (auth context). The auth path already validates
    JWT per-request; caching it would invent staleness for marginal gain.
  * Write paths. We don't write-through to Redis.
  * Search / vector retrieval. Those are pgvector-native; Redis can't
    replicate the math.

Sizing: a small Upstash plan (256 MB) holds ~50,000 cache entries at
~5 KB avg. Eviction is LRU at the Redis level.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable, TypeVar
from uuid import UUID

logger = logging.getLogger(__name__)


_DEFAULT_TTL_SEC = 60
T = TypeVar("T")


def _key(*parts: Any) -> str:
    """Compose a cache key like `aec:cache:orgs:{org_id}:projects`."""
    return "aec:cache:" + ":".join(str(p) for p in parts)


async def _get_pool():
    """Lazy import of the worker's Redis pool. Returns None on failure
    so caching becomes a no-op rather than a hard error."""
    try:
        from workers.queue import get_pool

        return await get_pool()
    except Exception as exc:
        logger.debug("cache: redis unavailable (%s) — running without cache", exc)
        return None


async def get_or_compute(
    key_parts: tuple[Any, ...],
    compute: Callable[[], Awaitable[T]],
    *,
    ttl_seconds: int = _DEFAULT_TTL_SEC,
) -> T:
    """Read-through cache.

    Tries Redis first; on miss, runs `compute()` and stores the JSON-
    serialised result. Any Redis error → fall through to compute (the
    caller's request shouldn't fail because of cache infra).

    Caller decides if `compute()` returns a serialisable shape. Pydantic
    models should be `.model_dump(mode="json")`-ed before they reach
    this function, or callers will hit a TypeError at `json.dumps`.
    """
    pool = await _get_pool()
    cache_key = _key(*key_parts)

    if pool is not None:
        try:
            raw = await pool.get(cache_key)
        except Exception as exc:
            logger.debug("cache.get failed for %s: %s", cache_key, exc)
            raw = None
        if raw is not None:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("cache: corrupt value at %s — recomputing", cache_key)

    # Miss path
    value = await compute()
    if pool is not None:
        try:
            await pool.set(cache_key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception as exc:
            logger.debug("cache.set failed for %s: %s", cache_key, exc)
    return value


async def invalidate(*key_parts: Any) -> None:
    """Drop a single cache entry. Call from write paths after mutating
    the source-of-truth row.

    Example:
        # In POST /projects:
        await invalidate("orgs", org_id, "projects")
    """
    pool = await _get_pool()
    if pool is None:
        return
    try:
        await pool.delete(_key(*key_parts))
    except Exception as exc:
        logger.debug("cache.invalidate failed: %s", exc)


async def invalidate_org_surface(org_id: UUID | str, surface: str) -> None:
    """Drop every cache entry for one org's surface using KEYS * scan.

    SCAN-based deletion avoids the O(n) global-block of `KEYS *`.
    Cap at 1000 keys per call — should never approach that in
    practice but stops a typo from melting Redis.
    """
    pool = await _get_pool()
    if pool is None:
        return
    pattern = _key("orgs", org_id, surface, "*")
    deleted = 0
    try:
        async for k in pool.scan_iter(match=pattern, count=200):
            await pool.delete(k)
            deleted += 1
            if deleted >= 1000:
                break
    except Exception as exc:
        logger.debug("cache.invalidate_org_surface failed: %s", exc)
