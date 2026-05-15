"""Token minting + verification for the subcontractor portal.

Mirrors services/rfq_tokens.py — same secret + algorithm — but with
different audience claim (`aec:subcontractor-portal`) so an RFQ
token can't accidentally unlock the subcontractor portal and vice
versa.

The token is the only credential the subcontractor presents. We
store SHA-256 of the token in the DB so a leaked DB dump cannot be
used to log in directly — the attacker would need to also have the
raw token from a Zalo conversation.

Token shape (JWT, ~250 bytes):
    iss: "aec-platform"
    aud: "aec:subcontractor-portal"
    sub: <grant_id>
    org: <organization_id>
    proj: <project_id>
    email: <subcontractor_email>
    exp: <epoch>
    iat: <epoch>
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from uuid import UUID

import jwt

from core.config import get_settings


_AUDIENCE = "aec:subcontractor-portal"
_ISSUER = "aec-platform"
_DEFAULT_TTL_DAYS = 365


@dataclass(frozen=True)
class SubcontractorTokenClaims:
    grant_id: UUID
    organization_id: UUID
    project_id: UUID
    email: str
    expires_at: int


class TokenError(Exception):
    """Token failed verification."""


def hash_token(raw_token: str) -> str:
    """SHA-256 hex of the raw token. Used as the DB stored form so a
    DB leak doesn't expose usable tokens directly."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def mint_subcontractor_token(
    *,
    grant_id: UUID,
    organization_id: UUID,
    project_id: UUID,
    email: str,
    ttl_days: int = _DEFAULT_TTL_DAYS,
) -> str:
    """Mint a signed JWT for one subcontractor's portal access.

    Caller is responsible for persisting `hash_token(returned_token)`
    to `subcontractor_portal_grants.token_hash` immediately after
    minting — the raw token only exists during the response to the
    admin's mint API call.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + ttl_days * 86_400,
        "sub": str(grant_id),
        "org": str(organization_id),
        "proj": str(project_id),
        "email": email,
    }
    return jwt.encode(
        payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm
    )


def verify_subcontractor_token(token: str) -> SubcontractorTokenClaims:
    """Verify + decode a subcontractor-portal token.

    Raises `TokenError` on any failure (bad signature, expired, wrong
    audience, missing claims). The public router turns that into HTTP
    401.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            options={"require": ["exp", "iat", "aud", "iss", "sub", "org", "proj"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("token audience mismatch — may be an RFQ token") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"invalid token: {exc}") from exc

    try:
        return SubcontractorTokenClaims(
            grant_id=UUID(payload["sub"]),
            organization_id=UUID(payload["org"]),
            project_id=UUID(payload["proj"]),
            email=payload.get("email", ""),
            expires_at=int(payload["exp"]),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed claims") from exc
