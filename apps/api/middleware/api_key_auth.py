"""Auth dependency that accepts EITHER a Supabase user JWT or an
`aec_…` API key.

Why a separate file (not extended `require_auth`):

  * `require_auth` is on every user-facing route. Folding api-key
    logic into it would (a) load Redis per request even when the
    caller is a logged-in user, and (b) widen the surface that's
    been heavily tested over months.

  * Public-facing API endpoints opt in by replacing
    `Depends(require_auth)` with `Depends(require_user_or_api_key)`.
    That makes the integration surface explicit — a future ops
    auditor can grep for it.

The `AuthContext` shape is shared with `require_auth` (same
`organization_id`, same role/user fields). For api-key callers, we
synthesise:
  * `user_id` = the api_key id (UUID), with role "api_key"
  * `organization_id` = api_key.organization_id
  * `email` = "" (no human attached)
The `scopes` for the call are stashed on a side-channel header
container so `require_scope(…)` can read them.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db.session import AdminSessionFactory
from middleware.auth import AuthContext, require_auth
from services.api_keys import (
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    KEY_PREFIX,
    check_rate_limit,
    has_scope,
    record_call,
    verify_key,
)

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=True)


# Stash the api-key's scopes on `request.state` so a later
# `require_scope` dependency can read them without re-querying. Lives
# on `request.state.api_key_scopes` (None when the caller is a user).


async def require_user_or_api_key(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    x_org_id: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """Resolve the caller from the Authorization header.

    Two paths:

      * Token starts with `aec_` → API key. Verify, rate-limit,
        synthesise an AuthContext.
      * Otherwise → assume Supabase JWT, defer to `require_auth`.

    Why we don't `Depends(require_auth)` from inside the api-key
    branch: `require_auth` requires `X-Org-ID`. API-key callers
    derive the org from the key itself, so we'd reject perfectly
    valid traffic. Splitting the path here avoids that.
    """
    raw = credentials.credentials
    if raw.startswith(KEY_PREFIX):
        return await _api_key_auth(request, raw)

    # User path — call require_auth manually so we keep the
    # existing JWT verification + RLS membership lookup.
    return await require_auth(credentials=credentials, x_org_id=x_org_id)


async def _api_key_auth(request: Request, raw: str) -> AuthContext:
    """Verify + rate-limit. Wrapped in its own helper so the user
    branch above stays a one-liner."""
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )

    async with AdminSessionFactory() as session:
        row = await verify_key(session=session, raw=raw, client_ip=client_ip)
        await session.commit()  # persist last_used_at + last_used_ip

    if row is None:
        # Bad key — nothing to attribute the failure to. We deliberately
        # don't write an api_key_calls row for unknown hashes (would
        # require persisting the bad hash, growing the table by spam).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    # Rate limit. Pull the redis pool lazily so a no-Redis dev
    # path doesn't fail to boot.
    redis = await _get_redis()
    # Explicit None check — `or DEFAULT` would falsy-coerce 0 (which
    # the migration's CHECK constraint rules out anyway, but defense
    # in depth: a stale row read shouldn't silently bypass a manually
    # zeroed-out limit).
    rl_override = row.get("rate_limit_per_minute")
    limit = rl_override if rl_override is not None else DEFAULT_RATE_LIMIT_PER_MINUTE
    allowed, count, lim = await check_rate_limit(
        redis,
        api_key_id=row["id"],
        limit_per_minute=limit,
    )
    # Attach the limit headers regardless of allowed-or-not so
    # well-behaved clients can pace themselves before they 429.
    request.state.rate_limit_count = count
    request.state.rate_limit_limit = lim

    # Record the call for usage telemetry. Fires for both allowed
    # and rate-limited requests so the dashboard's "error rate" tile
    # reflects 429s as failures. Best-effort: the writer swallows DB
    # errors internally so a telemetry hiccup can't break auth.
    async with AdminSessionFactory() as call_session:
        await record_call(call_session, api_key_id=row["id"], success=allowed)
        await call_session.commit()

    if not allowed:
        # 429 with a Retry-After hint (next minute boundary).
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        retry_after = 60 - now.second
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limit_exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    request.state.api_key_scopes = list(row["scopes"])
    request.state.api_key_id = row["id"]

    return AuthContext(
        user_id=row["id"],  # api_key id stands in for the actor uuid
        organization_id=row["organization_id"],
        role="api_key",
        email="",
    )


async def _get_redis():
    """Lazy redis pool — same connection settings as arq, kept
    independent so a worker-side outage doesn't break api auth."""
    try:
        from arq.connections import RedisSettings, create_pool

        from core.config import get_settings

        settings = get_settings()
        return await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as exc:  # pragma: no cover — dev path
        logger.warning("api_key rate limit: Redis unavailable (%s); permitting all", exc)
        return None


def require_scope(scope: str):
    """Gate a handler on a specific scope. No-op when the caller is
    a logged-in user (their org-membership role IS the authorisation;
    api-key scopes only apply to api-key callers).

    Use:
        @router.get("/projects")
        async def list_projects(
            auth: Annotated[AuthContext, Depends(require_user_or_api_key)],
            _scope = Depends(require_scope("projects:read")),
        ):
            ...
    """

    async def _dep(request: Request, auth: AuthContext = Depends(require_user_or_api_key)) -> None:
        if auth.role != "api_key":
            return  # users have implicit access via their role
        scopes = list(getattr(request.state, "api_key_scopes", []) or [])
        if not has_scope(scopes, scope):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"missing_scope: {scope}",
            )
        return

    return _dep
