from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from db.session import SessionFactory

bearer = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    organization_id: UUID
    role: str
    email: str


def _verify_jwt(token: str) -> dict:
    settings = get_settings()
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
