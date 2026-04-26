"""Stateless RFQ-supplier tokens for the public response portal.

When the dispatcher emails an RFQ to a supplier, the email contains a
URL like::

    https://app.example.com/rfq/respond?t=eyJhbGc…

The `t` query string is a JWT minted by `mint_response_token`. It's the
ONLY auth on the public endpoints — the supplier never logs in, never
sees the dashboard, never has an org. Verification proves three things:

  1. We minted it (signed with our `supabase_jwt_secret`).
  2. It's for the response flow (`aud == "rfq_response"`) — so a stolen
     dashboard JWT can't be replayed against the public endpoints, and
     vice versa.
  3. It hasn't expired (`exp` claim, default 60 days from mint).

Tokens are stateless on purpose: revocation happens by expiry. If a
supplier needs a re-issue, the dispatcher mints a fresh token and
emails again — the old one keeps working until expiry but lands on the
same RFQ.

The `(rfq_id, supplier_id)` pair is the natural key for the response
slot inside `rfqs.responses[]` — see `services.rfq_dispatch` for how
that JSONB array is populated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

import jwt

from core.config import get_settings

_AUDIENCE = "rfq_response"
_ISSUER = "aec-platform"


@dataclass(frozen=True)
class RfqTokenClaims:
    """Verified-then-typed token contents."""

    rfq_id: UUID
    supplier_id: UUID
    expires_at: int
    """Unix epoch seconds the token expires at — informational only."""


class TokenError(Exception):
    """Token failed verification — bad signature, wrong audience, expired, malformed."""


def mint_response_token(*, rfq_id: UUID, supplier_id: UUID, ttl_seconds: int | None = None) -> str:
    """Mint a signed JWT scoping a supplier to one RFQ-response slot.

    `ttl_seconds` defaults to the platform-wide `rfq_token_ttl_seconds`
    setting (60 days). Pass an explicit value when minting in a context
    that needs a tighter window — e.g. a "preview" link in a draft email.
    """
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.rfq_token_ttl_seconds
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        "rfq_id": str(rfq_id),
        "supplier_id": str(supplier_id),
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm)


def verify_response_token(token: str) -> RfqTokenClaims:
    """Verify + decode a supplier-portal token.

    Raises `TokenError` on any failure (bad signature, expired, wrong
    audience, missing or malformed claims). The caller — the public
    response endpoint — turns that into an HTTP 401.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            # `verify_aud` is on by default when `audience` is passed; making
            # it explicit guards against future PyJWT default changes.
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidAudienceError as exc:
        # A dashboard JWT has aud=Supabase project; would land here.
        raise TokenError("token has wrong audience") from exc
    except jwt.PyJWTError as exc:
        raise TokenError(f"token invalid: {exc}") from exc

    rfq_id_raw = payload.get("rfq_id")
    supplier_id_raw = payload.get("supplier_id")
    if not isinstance(rfq_id_raw, str) or not isinstance(supplier_id_raw, str):
        raise TokenError("token missing rfq_id/supplier_id")
    try:
        rfq_id = UUID(rfq_id_raw)
        supplier_id = UUID(supplier_id_raw)
    except ValueError as exc:
        raise TokenError(f"token has malformed UUID: {exc}") from exc

    return RfqTokenClaims(
        rfq_id=rfq_id,
        supplier_id=supplier_id,
        expires_at=int(payload["exp"]),
    )


def build_response_url(*, rfq_id: UUID, supplier_id: UUID, base_url: str | None = None) -> str:
    """Mint a token and build the full public response URL.

    `base_url` defaults to `settings.public_web_url`. Override only in
    tests or in tooling that needs to construct a link for a different
    deployment (e.g. cross-region staging email sender).
    """
    settings = get_settings()
    token = mint_response_token(rfq_id=rfq_id, supplier_id=supplier_id)
    base = (base_url or settings.public_web_url).rstrip("/")
    return f"{base}/rfq/respond?t={token}"
