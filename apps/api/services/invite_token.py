"""Project member invite token validator (cycle AAA1).

Signed token format for project-member invitation links. Token
shape: `<base64url(canonical_payload)>.<hmac_sha256_hex>`.

  build_invite_token(payload, secret, now)   — token string
  parse_invite_token(token, secret, now)     — InvitePayload or None
  InvitePayload                              — frozen dataclass

Composes FIVE prior cycles:
  * UU3 (`hmac_compare.safe_compare`) — constant-time signature compare.
  * GG3 (`email.parse_email`)         — invitee email validation.
  * YY2 (`tz_iso.to_iso/parse_iso`)   — `expires_at` round-trip.
  * PP3 (`canonical_query.build`)     — deterministic signing payload.
  * RR2 (`parse_query.parse_query`)   — token decode round-trip.

Pinned invariants:
  * HMAC-SHA256 over the canonical-query-encoded payload —
    deterministic across runs.
  * Tampered tokens (signature mismatch) → None.
  * Expired tokens (`now >= expires_at`) → None.
  * Malformed base64 / canonical query → None.
  * Token format is `<payload>.<signature>` (last `.` separates).
  * `MAX_INVITE_VALIDITY_DAYS = 30` enforced at build time
    (defends against issuing tokens that outlive their
    operational purpose).
  * Signature checked BEFORE expiry (constant-time signature
    compare; expiry comparison is non-secret).

Pure stdlib + UU3 + GG3 + YY2 + PP3 + RR2.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from services.canonical_query import build_canonical_query
from services.email import parse_email
from services.hmac_compare import safe_compare
from services.parse_query import parse_query
from services.tz_iso import parse_iso, to_iso

# Cap on validity window. Defends against tokens that sit
# around for longer than their operational purpose (e.g. an
# invite token leaked in 2027 logs is useless if it expired
# 30 days after 2026 issuance).
MAX_INVITE_VALIDITY_DAYS = 30


@dataclass(frozen=True)
class InvitePayload:
    """Decoded invite token payload."""

    org_id: str
    invitee_email: str
    expires_at: datetime  # tz-aware


def _payload_to_canonical(payload: InvitePayload) -> str:
    """Encode payload as canonical query string for signing."""
    return build_canonical_query(
        {
            "org_id": payload.org_id,
            "email": payload.invitee_email,
            "expires_at": to_iso(payload.expires_at),
        }
    )


def _sign(canonical: str, secret: str) -> str:
    """HMAC-SHA256 over the canonical payload, hex-encoded."""
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_invite_token(
    payload: InvitePayload,
    secret: str,
    now: datetime,
) -> str:
    """Build a signed invite token.

    Raises ValueError if:
      * `secret` is empty.
      * `payload.org_id` is empty.
      * `payload.invitee_email` is invalid (per GG3).
      * `expires_at` <= `now` (must be in the future).
      * `expires_at` > `now + MAX_INVITE_VALIDITY_DAYS`.
    """
    if not secret:
        raise ValueError("secret is required")
    if not payload.org_id:
        raise ValueError("org_id is required")
    if parse_email(payload.invitee_email) is None:
        raise ValueError(f"invalid email: {payload.invitee_email!r}")

    if payload.expires_at <= now:
        raise ValueError("expires_at must be in the future")

    max_expires = now + timedelta(days=MAX_INVITE_VALIDITY_DAYS)
    if payload.expires_at > max_expires:
        raise ValueError(f"expires_at exceeds MAX_INVITE_VALIDITY_DAYS={MAX_INVITE_VALIDITY_DAYS}")

    canonical = _payload_to_canonical(payload)
    payload_b64 = base64.urlsafe_b64encode(canonical.encode("utf-8")).rstrip(b"=").decode("ascii")
    signature = _sign(canonical, secret)
    return f"{payload_b64}.{signature}"


def parse_invite_token(
    token: str | None,
    secret: str,
    now: datetime,
) -> InvitePayload | None:
    """Parse and verify a signed invite token.

    Returns None for:
      * Empty token / secret.
      * Malformed base64 / canonical query / ISO date.
      * Tampered signature (constant-time compare via UU3).
      * Expired token (`now >= expires_at`).
    """
    if not token or not secret:
        return None
    if "." not in token:
        return None

    payload_b64, _, signature_hex = token.rpartition(".")
    if not payload_b64 or not signature_hex:
        return None

    # Re-add base64 padding for decode.
    pad_len = (-len(payload_b64)) % 4
    padded = payload_b64 + "=" * pad_len
    try:
        canonical_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error):
        return None
    try:
        canonical = canonical_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None

    # Parse the canonical query back to fields.
    parsed = parse_query(canonical)
    org_id = parsed.get("org_id")
    email = parsed.get("email")
    expires_at_iso = parsed.get("expires_at")

    # Type + presence validation.
    if not isinstance(org_id, str) or not org_id:
        return None
    if not isinstance(email, str) or not email:
        return None
    if not isinstance(expires_at_iso, str) or not expires_at_iso:
        return None

    expires_at = parse_iso(expires_at_iso)
    if expires_at is None:
        return None

    # Verify signature FIRST (constant-time via UU3 safe_compare).
    expected_sig = _sign(canonical, secret)
    if not safe_compare(signature_hex, expected_sig):
        return None

    # Then check expiry (non-secret comparison).
    if now >= expires_at:
        return None

    return InvitePayload(
        org_id=org_id,
        invitee_email=email,
        expires_at=expires_at,
    )
