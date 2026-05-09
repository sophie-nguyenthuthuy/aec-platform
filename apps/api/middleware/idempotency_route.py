"""FastAPI custom APIRoute that transparently handles
`Idempotency-Key` for POST/PATCH/DELETE requests.

Usage on a router:

    from middleware.idempotency_route import IdempotentRoute

    router = APIRouter(prefix="/api/v1/projects", route_class=IdempotentRoute)

    @router.post("")
    async def create(...): ...

Every POST/PATCH/DELETE on that router now:

  * Reads the `Idempotency-Key` header (when present).
  * Hashes the request body deterministically.
  * Looks up the (api_key_id, key) in `idempotency_records`.
  * On match → replays the cached response (handler not invoked).
  * On hash mismatch → returns 422.
  * On miss → invokes the handler, then caches the response on
    success (2xx).

Why a custom route class instead of middleware:
  * FastAPI dependencies (auth) run INSIDE the route — middleware
    can't see the resolved AuthContext. The route class hooks at
    the right layer.
  * Body re-injection is handled by Starlette's `Request.body()`
    caching: once we call `await request.body()` here, subsequent
    calls (including the handler reading its body) return the same
    bytes without re-reading the stream.
  * Skipping idempotency for non-api-key callers + GETs is a
    one-line check at the route level.

What this does NOT do:
  * Apply to user-JWT callers. Idempotency is keyed on api_key_id;
    extending to users would need an extra column in the PK.
  * Cache 4xx/5xx responses. Replaying a server error is a worse
    outcome than re-running the handler. Spec mirrors Stripe.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from db.session import AdminSessionFactory
from services.api_keys import KEY_PREFIX, hash_key
from services.idempotency import (
    MAX_KEY_LEN,
    hash_body,
    lookup_or_lock,
    persist_response,
)

logger = logging.getLogger(__name__)


# Methods that participate in the idempotency dance. GETs are
# read-only — caching them under an idempotency key would just be
# response caching by another name (and we have HTTP cache headers
# for that). HEAD/OPTIONS are skipped for the same reason.
_MUTATING_METHODS = frozenset({"POST", "PATCH", "DELETE", "PUT"})


class IdempotentRoute(APIRoute):
    """APIRoute subclass that wraps the handler with idempotency
    logic. Activate per-router via `route_class=IdempotentRoute`."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def custom(request: Request) -> Response:
            # Fast paths: no header, non-mutating method, or non-api-key
            # auth — fall through to the handler unchanged. These cases
            # are the majority of traffic; the cost of `request.headers`
            # is a dict lookup.
            if request.method not in _MUTATING_METHODS:
                return await original(request)
            key = request.headers.get("idempotency-key")
            if not key:
                return await original(request)
            if len(key) > MAX_KEY_LEN:
                # Reject before hashing a potentially-large body.
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"idempotency_key_too_long: max {MAX_KEY_LEN} chars",
                )

            # Resolve the api_key_id from the Authorization header
            # WITHOUT running the full auth dependency (that happens
            # later, inside `original`). We just need the FK target
            # for the lookup. User-JWT callers don't have an api-key
            # id and silently skip the idempotency dance.
            api_key_id = await _resolve_api_key_id(request)
            if api_key_id is None:
                return await original(request)

            # Read + hash the body. `request.body()` caches the bytes
            # on the Request object so the downstream handler reading
            # `await request.body()` (or pydantic body parsing) sees
            # the same bytes — Starlette handles re-injection.
            body_bytes = await request.body()
            request_hash = hash_body(body_bytes)

            async with AdminSessionFactory() as session:
                result = await lookup_or_lock(
                    session,
                    api_key_id=api_key_id,
                    key=key,
                    request_hash=request_hash,
                    method=request.method,
                    path=request.url.path,
                )
                # Note: lookup_or_lock acquires `FOR UPDATE`. We must
                # commit (or rollback) before the handler runs —
                # otherwise concurrent retries deadlock waiting on
                # this row.
                await session.commit()

            if result.cached:
                # Replay the cached response byte-identical to the
                # original. The body is the JSON envelope the handler
                # returned; we re-serialise via JSONResponse.
                return JSONResponse(
                    content=result.cached_body,
                    status_code=result.cached_status or 200,
                    headers={"X-AEC-Idempotent-Replay": "true"},
                )
            if result.mismatch:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "idempotency_key_reused_with_different_body",
                )

            # Fresh: run the handler, capture the response, persist on success.
            response = await original(request)
            if 200 <= response.status_code < 300:
                # Best-effort cache. We need the response body bytes;
                # JSONResponse exposes `.body` directly.
                body_to_cache = _extract_response_body(response)
                if body_to_cache is not None:
                    async with AdminSessionFactory() as session:
                        await persist_response(
                            session,
                            api_key_id=api_key_id,
                            key=key,
                            request_hash=request_hash,
                            method=request.method,
                            path=request.url.path,
                            response_status=response.status_code,
                            response_body=body_to_cache,
                        )
                        await session.commit()
            return response

        return custom


# ---------- Helpers ----------


async def _resolve_api_key_id(request: Request) -> Any:
    """Lift the api_key_id from the Authorization header without
    invoking the full auth dependency. Returns None when the caller
    isn't an api-key user (JWT user, no auth, malformed header) —
    those paths skip idempotency.

    We re-do the hash + DB lookup here (rather than reading from
    `request.state` which only the auth dep populates) because this
    runs BEFORE the handler — and therefore before the dep — by
    design. The cost is one extra SELECT on the hot path of
    idempotent writes; trade-off accepted.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    raw = auth_header.split(" ", 1)[1].strip()
    if not raw.startswith(KEY_PREFIX):
        return None
    h = hash_key(raw)
    from sqlalchemy import text as sql_text

    async with AdminSessionFactory() as session:
        result = await session.execute(
            sql_text(
                """
                SELECT id FROM api_keys
                WHERE hash = :h AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > NOW())
                """
            ),
            {"h": h},
        )
        row = result.scalar_one_or_none()
    return row


def _extract_response_body(response: Response) -> Any:
    """Pull a JSON-decodable body off the response object. Best-
    effort: returns None if the response isn't a JSON envelope (e.g.
    StreamingResponse, plaintext) — those routes can't be cached.
    """
    body = getattr(response, "body", None)
    if not body:
        return None
    try:
        return json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
