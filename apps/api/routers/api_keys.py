"""CRUD endpoints for per-org API keys.

Three endpoints:

  * `POST  /api/v1/api-keys`   — mint. Returns the plaintext key in
    the response body **once**. Caller stores it; we keep the hash.
  * `GET   /api/v1/api-keys`   — list (active + revoked). Returns
    metadata only — no plaintext, no hash.
  * `POST  /api/v1/api-keys/{id}/revoke` — soft-delete. Sets
    `revoked_at = NOW()`, which removes the key from the partial
    auth-lookup index.

Admin-gated: minting an API key is a destructive privilege (a leaked
key is a tenant-wide compromise). Admins only.

The schema route lives at `GET /api/v1/api-keys/scopes` so the
frontend can render the create-form's scope checkboxes from the
canonical list without duplicating the vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext
from middleware.idempotency_route import IdempotentRoute
from middleware.rbac import Role, require_min_role
from services.api_keys import SCOPES, mint_key

# `route_class=IdempotentRoute` opts every POST/PATCH/DELETE on this
# router into the `Idempotency-Key` header contract. Documented in
# `/docs/api#idempotency`. The api-keys mint endpoint is the highest-
# value retry-safety target on the platform: a partner whose CI tries
# to provision a key, times out, retries — without idempotency, gets
# two keys, one of which leaks the secret without ever being consumed.
router = APIRouter(
    prefix="/api/v1/api-keys",
    tags=["api-keys"],
    route_class=IdempotentRoute,
)


class ApiKeyCreate(BaseModel):
    """Mint payload. The frontend collects these from the form."""

    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    # ISO-8601 timestamp; None = never expires.
    expires_at: datetime | None = None
    mode: str = Field(default="live", pattern="^(live|test)$")
    # Per-project allowlist. Empty list (default) = "all projects" —
    # the back-compat shape that pre-0039 keys had. A non-empty list
    # is a closed allowlist; the key gets 403 on any project outside
    # it via `require_project_scope` on tagged routes.
    project_ids: list[UUID] = Field(default_factory=list)


@router.get("/scopes")
async def list_scopes(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Canonical scope vocabulary — drives the create-form checkboxes
    on `/settings/api-keys`. Returned sorted so the UI renders them
    deterministically."""
    return ok(sorted(SCOPES))


@router.post("", status_code=201)
async def create_api_key(
    payload: ApiKeyCreate,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Mint a new key. The plaintext is in the response body — flag
    it loudly to the user that THIS is the only time they see it.

    The `*` (full-org) scope is admin-only on top of the route-level
    admin gate; we don't currently distinguish org-admin from
    platform-admin, so this is a no-op today. Left as a hook for
    when the role system gets that distinction.
    """
    try:
        async with TenantAwareSession(auth.organization_id) as session:
            raw, row = await mint_key(
                session,
                organization_id=auth.organization_id,
                created_by=auth.user_id,
                name=payload.name,
                scopes=payload.scopes,
                rate_limit_per_minute=payload.rate_limit_per_minute,
                expires_at=payload.expires_at,
                mode=payload.mode,
                project_ids=payload.project_ids,
            )
            await session.commit()
    except ValueError as exc:
        # Bad scope. Surface the message; pydantic-style 422 would
        # be nicer but the validation is service-side (depends on
        # the SCOPES set) so 400 is the right code.
        raise HTTPException(400, str(exc)) from exc

    return ok(
        {
            "id": str(row["id"]),
            "name": row["name"],
            "prefix": row["prefix"],
            "scopes": row["scopes"],
            "rate_limit_per_minute": row["rate_limit_per_minute"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "last_used_at": None,
            "revoked_at": None,
            "created_at": row["created_at"].isoformat(),
            "mode": row.get("mode", "live"),
            "project_ids": [str(p) for p in (row.get("project_ids") or [])],
            # The plaintext — shown once.
            "key": raw,
        }
    )


@router.get("")
async def list_api_keys(
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
) -> dict[str, Any]:
    """All keys for the calling org (active + revoked), newest first.
    Returns metadata only — no plaintext, no hash. The `prefix` is
    enough for users to identify a row."""
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, name, prefix, scopes, rate_limit_per_minute,
                               last_used_at, last_used_ip, revoked_at,
                               expires_at, created_at, mode, project_ids
                        FROM api_keys
                        ORDER BY created_at DESC
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
    return ok(
        [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "prefix": r["prefix"],
                "scopes": r["scopes"],
                "rate_limit_per_minute": r["rate_limit_per_minute"],
                "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
                "last_used_ip": r["last_used_ip"],
                "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "created_at": r["created_at"].isoformat(),
                "mode": r.get("mode") or "live",
                "project_ids": [str(p) for p in (r.get("project_ids") or [])],
            }
            for r in rows
        ]
    )


@router.post("/{key_id}/revoke", status_code=200)
async def revoke_api_key(
    key_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Soft-delete: set `revoked_at = NOW()`. Idempotent — calling
    twice on an already-revoked key returns the existing
    `revoked_at` instead of bumping it.

    The partial index `ix_api_keys_hash_active` is `WHERE revoked_at
    IS NULL`, so a revoked row drops out of the auth lookup
    immediately — no separate cache invalidation needed.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                """
                UPDATE api_keys
                SET revoked_at = COALESCE(revoked_at, NOW())
                WHERE id = :id
                RETURNING id, revoked_at
                """
            ),
            {"id": str(key_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "api_key_not_found")
        await session.commit()

    return ok(
        {
            "id": str(row["id"]),
            "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
        }
    )
