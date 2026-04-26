from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from db.session import SessionFactory

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    organization_id: UUID
    role: str
    email: str


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient | None:
    """Build a process-wide JWKS client for Supabase ES256 verification.

    Returns None when SUPABASE_URL is unset, in which case `_verify_jwt`
    falls back to HS256 with the legacy shared secret. PyJWKClient caches
    keys by `kid`, so the JWKS endpoint is only hit on the first token of
    each rotation generation.
    """
    settings = get_settings()
    url = settings.supabase_url
    if not url:
        return None
    jwks_url = f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=600)


def _verify_jwt(token: str) -> dict:
    settings = get_settings()
    client = _jwks_client()

    # New path: Supabase asymmetric JWTs (ES256/EdDSA via JWKS endpoint).
    # Audience is always "authenticated" for Supabase user sessions.
    # `leeway` tolerates small clock drift between Supabase's edge and the
    # api container — without it, Docker hosts that are even a second
    # behind hit `ImmatureSignatureError` on freshly-issued tokens.
    if client is not None:
        try:
            signing_key = client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "EdDSA", "RS256"],
                audience="authenticated",
                leeway=60,
            )
        except jwt.PyJWTError as exc:
            logger.warning("JWT verification failed: %s", exc)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    # Fallback: legacy HS256 with shared secret. Used by tests and any
    # deployment that hasn't migrated to the asymmetric key system yet.
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc


async def _resolve_membership(session: AsyncSession, user_id: UUID, org_id: UUID) -> str:
    result = await session.execute(
        text("SELECT role FROM org_members WHERE user_id = :u AND organization_id = :o"),
        {"u": str(user_id), "o": str(org_id)},
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organization")
    return role


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    x_org_id: str | None = Header(default=None),
) -> AuthContext:
    if not x_org_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing X-Org-ID header")
    try:
        org_id = UUID(x_org_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Org-ID") from exc

    payload = _verify_jwt(credentials.credentials)
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing subject")
    try:
        user_id = UUID(user_id_raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user id") from exc

    async with SessionFactory() as session:
        role = await _resolve_membership(session, user_id, org_id)

    return AuthContext(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        email=payload.get("email", ""),
    )


def require_role(*allowed: str):
    async def _dep(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return ctx

    return _dep


@dataclass(frozen=True)
class UserContext:
    """JWT-validated user with no org context. Used by `/me/*` endpoints
    that must work *before* an org is pinned (e.g. listing org memberships
    so the UI can render an org switcher)."""

    user_id: UUID
    email: str


async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> UserContext:
    payload = _verify_jwt(credentials.credentials)
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing subject")
    try:
        user_id = UUID(user_id_raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user id") from exc
    return UserContext(user_id=user_id, email=payload.get("email", ""))
