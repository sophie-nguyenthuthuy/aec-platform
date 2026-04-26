"""Unit tests for the RFQ supplier-portal token utility.

These tests don't touch Postgres or Redis — they exercise the JWT
mint/verify roundtrip and its failure modes (tampering, expiry, wrong
audience). Integration tests in `test_public_rfq_router.py` cover the
endpoint plumbing on top of these primitives.
"""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from core.config import get_settings
from services.rfq_tokens import (
    TokenError,
    build_response_url,
    mint_response_token,
    verify_response_token,
)


def test_mint_then_verify_roundtrips_uuids():
    rfq_id = uuid4()
    supplier_id = uuid4()
    token = mint_response_token(rfq_id=rfq_id, supplier_id=supplier_id)
    claims = verify_response_token(token)
    assert claims.rfq_id == rfq_id
    assert claims.supplier_id == supplier_id
    # 60-day default TTL should leave us a long way in the future.
    assert claims.expires_at > time.time() + 60 * 60 * 24 * 30


def test_verify_rejects_tampered_token():
    """A flipped byte in the signature must fail verification."""
    token = mint_response_token(rfq_id=uuid4(), supplier_id=uuid4())
    # Flip the last char of the signature segment.
    last = token[-1]
    flipped = "a" if last != "a" else "b"
    tampered = token[:-1] + flipped
    with pytest.raises(TokenError):
        verify_response_token(tampered)


def test_verify_rejects_expired_token():
    """A negative TTL forces immediate expiry."""
    token = mint_response_token(rfq_id=uuid4(), supplier_id=uuid4(), ttl_seconds=-1)
    with pytest.raises(TokenError, match="expired"):
        verify_response_token(token)


def test_verify_rejects_dashboard_audience_jwt():
    """A token signed with our secret but for the dashboard audience must fail.

    Dashboard JWTs (issued by Supabase) carry `aud` set to the project ref —
    NOT `rfq_response`. A leaked dashboard token must not unlock public
    endpoints, and vice versa.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": "supabase",
        "aud": "authenticated",  # what Supabase actually sets
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + 3600,
        "rfq_id": str(uuid4()),
        "supplier_id": str(uuid4()),
    }
    bogus = jwt.encode(payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        verify_response_token(bogus)


def test_verify_rejects_token_signed_with_wrong_secret():
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": "aec-platform",
        "aud": "rfq_response",
        "iat": now,
        "exp": now + 3600,
        "rfq_id": str(uuid4()),
        "supplier_id": str(uuid4()),
    }
    bogus = jwt.encode(payload, settings.supabase_jwt_secret + "-wrong", algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        verify_response_token(bogus)


def test_verify_rejects_token_with_malformed_uuid():
    """A token whose claims are well-formed JWT but garbage UUIDs must fail.

    Forces TokenError rather than a 500 on the public endpoint when a
    custom-built token tries to slip in a non-UUID rfq_id.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": "aec-platform",
        "aud": "rfq_response",
        "iat": now,
        "exp": now + 3600,
        "rfq_id": "not-a-uuid",
        "supplier_id": str(uuid4()),
    }
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError, match="malformed UUID"):
        verify_response_token(token)


def test_build_response_url_contains_token_and_path():
    rfq_id = uuid4()
    supplier_id = uuid4()
    url = build_response_url(rfq_id=rfq_id, supplier_id=supplier_id, base_url="https://app.example.com")
    assert url.startswith("https://app.example.com/rfq/respond?t=")
    token = url.split("t=", 1)[1]
    # The embedded token must verify back to the same IDs.
    claims = verify_response_token(token)
    assert claims.rfq_id == rfq_id
    assert claims.supplier_id == supplier_id


def test_build_response_url_strips_trailing_slash_from_base():
    """Operators sometimes set `public_web_url` with a trailing slash.

    We don't want the resulting URL to contain `//rfq/respond` because
    some inboxes (Outlook in particular) collapse `//` and break the
    link silently.
    """
    url = build_response_url(
        rfq_id=uuid4(),
        supplier_id=uuid4(),
        base_url="https://app.example.com/",
    )
    assert "//rfq/respond" not in url
    assert "/rfq/respond?t=" in url
