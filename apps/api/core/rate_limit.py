"""Lightweight Redis-backed fixed-window rate limiter.

Why hand-roll instead of pulling `slowapi`:
  * The API surface we want is one ~6-line FastAPI dependency. The full
    flask-limiter port carries decorators, multiple storage backends,
    and middleware glue we don't use.
  * Storage works on the same Redis URL the queue already uses
    (`settings.redis_url`), so no new ops dependency.

The algorithm is a fixed-window counter:

    INCR rl:<prefix>:<key>
    if returned == 1:
        EXPIRE rl:<prefix>:<key> <window_sec>
    if returned > limit:
        429

Fixed-window has the classic "burst at the boundary" pathology
(2 × limit requests in 2s if a client times the window flip), but it's
fine for the scale we care about — abuse-prevention on auth/invitation
endpoints, not strict QoS. If we ever need precise budgets we'll graduate
to a token bucket; the dependency surface below stays the same so callers
don't have to change.

Public surface:

    rate_limit(prefix="invite-accept", limit=10, window_sec=60)
        — returns a FastAPI dependency that 429s when exceeded.

    The dependency keys on `request.client.host` (the caller IP). For
    authenticated routes the caller's UUID is a better key — wire that
    explicitly via the `key_fn` parameter:

        rate_limit(
            prefix="me-orgs",
            limit=60,
            window_sec=60,
            key_fn=lambda req, auth: str(auth.user_id),
        )

If Redis is unreachable we **fail open** (allow the request) rather than
break the api. Rate limiting is a defense-in-depth control — Supabase
and the api's own auth gates are the primary line — so an outage in the
limiter shouldn't take the api down with it. The decision is logged so
ops can spot it; a misbehaving Redis won't be silent.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


# Type for an optional key extraction function. Receives the FastAPI
# Request plus any Depends-injected context (e.g. AuthContext). Should
# return a stable string used as the bucket key.
KeyFn = Callable[..., str]


async def _acquire(redis_url: str, key: str, limit: int, window_sec: int) -> bool:
    """Increment + maybe-expire. Returns True if the request is allowed.

    Implementation note: we open + close a connection per call. That's
    ~1ms of overhead which is acceptable for the auth/invite paths
    (called once per HTTP request), and it sidesteps the global-pool
    lifecycle question. If a hot path emerges we'll graduate to an
    arq-style pooled client.
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover — `redis` is in requirements.txt
        logger.warning("rate_limit: redis package not installed; failing open")
        return True

    try:
        client = aioredis.from_url(redis_url, decode_responses=True)
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window_sec)
            return count <= limit
        finally:
            await client.aclose()
    except Exception as exc:
        # Redis outage / DNS flap / connection refused. Fail open and
        # log loudly so ops dashboards catch the regression — but don't
        # 5xx the user's request just because the limiter is degraded.
        logger.warning("rate_limit: redis unreachable (%s); failing open for key=%s", exc, key)
        return True


def rate_limit(
    *,
    prefix: str,
    limit: int,
    window_sec: int,
    key_dep: Any | None = None,
) -> Callable[..., Awaitable[None]]:
    """Build a FastAPI dependency that 429s when the bucket overflows.

    `prefix` namespaces buckets so two endpoints with the same key (e.g.
    same client IP) don't share a counter. `limit` is the max requests
    allowed in the rolling `window_sec`-second window.

    `key_dep` is an optional FastAPI dependency that resolves to the
    bucket-key string. Default behavior (when `None`) keys on the
    caller's IP. Authenticated routes that want to key on user_id should
    pass a small `Depends(...)` like:

        def _user_key(user: UserContext = Depends(require_user)) -> str:
            return str(user.user_id)

        rate_limit(prefix="me-orgs", limit=60, window_sec=60,
                   key_dep=Depends(_user_key))

    Why a Depends instead of a plain callable: FastAPI introspects the
    dependency's signature to know which parameters to inject, and
    declaring `**kwargs` on the wrapper accidentally surfaces a `kwargs`
    query parameter on every protected endpoint. Routing the key via
    `Depends(...)` lets FastAPI resolve the chain properly.
    """

    if key_dep is None:

        async def _dep_ip(request: Request) -> None:
            client = request.client
            key_value = client.host if client else "unknown"
            await _check(prefix, key_value, limit, window_sec)

        return _dep_ip

    async def _dep_keyed(key_value: str = key_dep) -> None:
        await _check(prefix, key_value, limit, window_sec)

    return _dep_keyed


async def _check(prefix: str, key_value: str, limit: int, window_sec: int) -> None:
    from core.config import get_settings

    settings = get_settings()
    full_key = f"rl:{prefix}:{key_value}"
    allowed = await _acquire(settings.redis_url, full_key, limit, window_sec)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Limit: {limit} per {window_sec}s.",
            headers={"Retry-After": str(window_sec)},
        )
