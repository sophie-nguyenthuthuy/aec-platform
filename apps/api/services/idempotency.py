"""Idempotency-Key replay cache for retried POST/PATCH/DELETE.

Industry-standard contract (Stripe, Square): partner's system sends
`Idempotency-Key: <uuid>` with a write request. If we've seen the key
before, replay the original response instead of running the handler
again. Keeps retries safe across network blips.

Three responsibilities:

  1. **Canonicalise + hash the body** so the same JSON with reordered
     keys hashes the same. Stripe rejects "different body, same key"
     with 422 — we mirror that.

  2. **Lookup-or-lock** at the start of a handler: if a previous
     record matches, replay; if a previous record exists with a
     DIFFERENT body hash on the same key, return 422; otherwise
     return None and let the handler run.

  3. **Persist response** at the end of a successful handler:
     INSERT the (api_key_id, key, request_hash, status, body) row
     so the next retry hits the cache.

Why this is a service module + dependency rather than middleware:
  * Middleware that intercepts request body + response body has to
    re-inject the body into the receive channel — fragile.
  * Handlers opting in keeps the contract explicit; an auditor can
    grep for `idempotency_check` to find every retry-safe write.
  * Auth context is already resolved by the time the handler runs;
    no need to redo the api-key hash lookup at middleware time.

Posture for non-api-key callers (Supabase JWT users):
  * v1: NO idempotency. Users don't usually retry on UI button
    clicks (the front-end disables on submit), and the org-scoped
    PK (api_key_id) doesn't have a clean substitute. Adding user
    support later means extending the PK; for now an `Idempotency-
    Key` header from a user request is silently ignored.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Cap: keys above this length are rejected with 400. The migration's
# CHECK constraint enforces it server-side too. 200 chars covers any
# sane UUID / nanoid encoding plus partner-prefixed conventions like
# `crm_sync_<uuid>`.
MAX_KEY_LEN = 200


# ---------- Canonicalisation ----------


def canonicalise_body(body: bytes | str | None) -> bytes:
    """Return a deterministic byte representation of `body` for
    hashing. JSON gets re-serialised with sorted keys + no
    whitespace; non-JSON bodies pass through unchanged.

    Sorting keys collapses semantically-identical payloads:
    `{"a":1,"b":2}` and `{"b":2,"a":1}` hash the same. Without this,
    a partner whose JSON serialiser orders keys differently across
    retries would never hit the cache.
    """
    if body is None or body == b"" or body == "":
        return b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        # Not JSON — hash bytes as-is. Multipart uploads, plain text,
        # etc. all flow through here.
        return body
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_body(body: bytes | str | None) -> str:
    """sha256-hex of the canonicalised body."""
    canonical = canonicalise_body(body)
    return hashlib.sha256(canonical).hexdigest()


# ---------- Lookup ----------


class IdempotencyResult:
    """Outcome of an idempotency check.

    Three states:
      * `cached`: replay this exact response (status + body).
      * `mismatch`: same key, different body — caller should 422.
      * `fresh`: no prior record; caller should run the handler and
        then call `persist_response`.

    `request_hash` is set in all three states so `persist_response`
    doesn't have to re-hash.
    """

    def __init__(
        self,
        *,
        request_hash: str,
        cached_status: int | None = None,
        cached_body: dict | None = None,
        mismatch: bool = False,
    ) -> None:
        self.request_hash = request_hash
        self.cached_status = cached_status
        self.cached_body = cached_body
        self.mismatch = mismatch

    @property
    def cached(self) -> bool:
        return self.cached_status is not None

    @property
    def fresh(self) -> bool:
        return not self.cached and not self.mismatch


async def lookup_or_lock(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    key: str,
    request_hash: str,
    method: str,
    path: str,
) -> IdempotencyResult:
    """Look up a prior record by `(api_key_id, key)`.

    Decision tree:
      * No prior row → `fresh`.
      * Prior row with matching `(request_hash, method, path)` →
        `cached` — caller replays the response.
      * Prior row with different hash/method/path → `mismatch` —
        caller 422s with a friendly message. We INTENTIONALLY include
        method+path in the match because Stripe-style "same key on
        different routes is wrong" catches subtle integration bugs.

    The query uses `FOR UPDATE` so a concurrent retry from the same
    partner serialises through this lookup — without it, two parallel
    retries could both find no row and both run the handler,
    defeating the whole purpose.
    """
    result = await session.execute(
        text(
            """
            SELECT request_hash, request_method, request_path,
                   response_status, response_body
            FROM idempotency_records
            WHERE api_key_id = :id AND key = :key
            FOR UPDATE
            """
        ),
        {"id": str(api_key_id), "key": key},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return IdempotencyResult(request_hash=request_hash)
    if row["request_hash"] == request_hash and row["request_method"] == method and row["request_path"] == path:
        return IdempotencyResult(
            request_hash=request_hash,
            cached_status=int(row["response_status"]),
            cached_body=dict(row["response_body"]),
        )
    return IdempotencyResult(request_hash=request_hash, mismatch=True)


# ---------- Persist ----------


async def maybe_handle(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    request: Any,  # fastapi.Request — typed Any to keep imports light
    method: str,
    path: str,
) -> IdempotencyResult | None:
    """High-level wrapper: parses the `Idempotency-Key` header off
    `request`, hashes the body, runs `lookup_or_lock`, returns the
    `IdempotencyResult` (or None if no header present, meaning
    "skip idempotency, run normally").

    Handlers call this at the top:

        async def create_project(req: Request, body: ProjectCreate, auth = Depends(...)):
            idem = await maybe_handle(session, api_key_id=auth.user_id, request=req,
                                      method="POST", path="/api/v1/projects")
            if idem and idem.cached:
                return JSONResponse(idem.cached_body, status_code=idem.cached_status)
            if idem and idem.mismatch:
                raise HTTPException(422, "idempotency_key_reused_with_different_body")
            ...do work...
            await persist_response(session, api_key_id=auth.user_id, key=...,
                                   request_hash=idem.request_hash, ...)

    Returns None when the caller didn't provide the header. The
    handler treats that as "no idempotency promised, behave normally".
    """
    key = request.headers.get("idempotency-key") if hasattr(request, "headers") else None
    if not key:
        return None
    if len(key) > MAX_KEY_LEN:
        # Out-of-band: the migration's CHECK would reject it on
        # INSERT, but we want to fail fast before we hash a 1MB body.
        # Raise a generic 400 — the caller's HTTPException handler
        # surfaces it cleanly.
        from fastapi import HTTPException, status

        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"idempotency_key_too_long: max {MAX_KEY_LEN} chars",
        )
    body_bytes = await request.body() if hasattr(request, "body") else b""
    request_hash = hash_body(body_bytes)
    return await lookup_or_lock(
        session,
        api_key_id=api_key_id,
        key=key,
        request_hash=request_hash,
        method=method,
        path=path,
    )


async def persist_response(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    key: str,
    request_hash: str,
    method: str,
    path: str,
    response_status: int,
    response_body: Any,
) -> None:
    """Cache the handler's response so future retries replay.

    Idempotent INSERT — `ON CONFLICT DO NOTHING` so a near-simultaneous
    second handler invocation that escaped the FOR UPDATE serialisation
    (extremely rare; possible across replicas) doesn't 500 with a PK
    violation. The first writer wins; the second's response is
    discarded but the user already got the same logical answer.
    """
    try:
        await session.execute(
            text(
                """
                INSERT INTO idempotency_records (
                    api_key_id, key, request_hash, request_method,
                    request_path, response_status, response_body
                ) VALUES (
                    :id, :key, :hash, :method, :path, :status,
                    CAST(:body AS JSONB)
                )
                ON CONFLICT (api_key_id, key) DO NOTHING
                """
            ),
            {
                "id": str(api_key_id),
                "key": key,
                "hash": request_hash,
                "method": method,
                "path": path,
                "status": response_status,
                "body": json.dumps(response_body, default=str),
            },
        )
    except Exception as exc:  # pragma: no cover — defensive
        # Cache failures must not break the user-facing response.
        # The original write committed; the next retry just won't hit
        # the cache and will execute the handler again — a worse
        # outcome than the cache hit, but still correct.
        logger.warning(
            "idempotency.persist_response failed for key=%s: %s — replay disabled for this key",
            key,
            exc,
        )
