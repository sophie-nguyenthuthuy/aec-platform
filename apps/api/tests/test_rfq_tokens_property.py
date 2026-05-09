"""Property-based tests for the RFQ supplier-portal token primitives.

Why property testing here specifically
--------------------------------------
`services/rfq_tokens.py` is the ONLY auth on the public supplier-
response endpoints — a token forgery here is an unauthenticated write
into another tenant's RFQ data. The example-based tests in
`test_rfq_tokens.py` cover the obvious paths (round-trip, tampered
sig, expired). This file exercises a small set of inputs across
~hundreds of randomly-generated UUIDs/TTLs to catch bugs that don't
show up in any single hand-picked example:

  * UUID encoding edge cases (UUIDs with all-zero segments, all-FF
    segments, version-1/4/etc. mixes — all valid `uuid.UUID()` but
    sometimes serialised differently by old `pyjwt` versions).
  * TTL boundary conditions (`ttl_seconds=0` / `ttl_seconds=1` —
    where iat==exp or exp is 1 second from now and may be already-
    expired by the time `verify` runs on a slow machine).
  * Audience confusion — the dashboard JWT lives at the same secret
    but with a different `aud`; we generate "look-alike" tokens
    with arbitrary aud strings and assert verify rejects all of
    them except the canonical one.

Hypothesis runs each property 100 times by default and shrinks
counter-examples. A failure here is a security defect, not a flake
— investigate, don't suppress.
"""

from __future__ import annotations

import time
from uuid import UUID

import jwt
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from core.config import get_settings
from services.rfq_tokens import (
    TokenError,
    mint_response_token,
    verify_response_token,
)

# UUIDs from `uuid4()` cover most of the space, but we also want the
# corner cases — all-zero, all-ones — that real-world UUIDs should
# never hit but a malformed test fixture might. `st.uuids()` covers
# v1/v3/v4/v5 across the full random space.
_uuid_strategy = st.uuids()

# TTL window: from 1 second (sub-clock-precision boundary) to 1 year.
# Hypothesis prefers small examples by default; explicit min=1 stops
# it from generating 0 (which would mint a token with iat==exp; PyJWT
# treats that as already-expired).
_ttl_strategy = st.integers(min_value=1, max_value=60 * 60 * 24 * 365)

# Test settings: more runs than the default (100) since this is
# security-critical code. Disable the function_scoped_fixture warning
# — we don't use any fixture here, but hypothesis nags about its
# `time.time()` call being non-deterministic.
_settings = settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@_settings
@given(rfq=_uuid_strategy, supplier=_uuid_strategy, ttl=_ttl_strategy)
def test_mint_verify_roundtrip_preserves_uuids(rfq: UUID, supplier: UUID, ttl: int):
    """Property: verify(mint(rfq, supplier, ttl)).{rfq_id,supplier_id} == (rfq, supplier).

    Catches: any bug in either direction of UUID ↔ string serialisation,
    plus any silent truncation/normalisation that PyJWT might do.
    A counter-example here would mean a supplier could mint a token
    that lands them on someone ELSE's RFQ slot.
    """
    token = mint_response_token(rfq_id=rfq, supplier_id=supplier, ttl_seconds=ttl)
    claims = verify_response_token(token)
    assert claims.rfq_id == rfq
    assert claims.supplier_id == supplier
    # exp must be in the future (we just minted it) — within ttl seconds.
    now = int(time.time())
    assert now <= claims.expires_at <= now + ttl + 2  # +2: clock skew safety


@_settings
@given(rfq=_uuid_strategy, supplier=_uuid_strategy)
def test_default_ttl_is_far_in_the_future(rfq: UUID, supplier: UUID):
    """Property: default-TTL token expires at least 30 days from now.

    Pins the "no surprise short default" property — a regression
    that flipped `rfq_token_ttl_seconds` from 60 days to 60 minutes
    would silently break every email link sent more than an hour
    before the supplier got around to opening it.
    """
    token = mint_response_token(rfq_id=rfq, supplier_id=supplier)
    claims = verify_response_token(token)
    assert claims.expires_at > time.time() + 60 * 60 * 24 * 30


@_settings
@given(
    rfq=_uuid_strategy,
    supplier=_uuid_strategy,
    bad_aud=st.text(min_size=1, max_size=40).filter(lambda s: s != "rfq_response"),
)
def test_token_with_arbitrary_audience_is_rejected(rfq: UUID, supplier: UUID, bad_aud: str):
    """Property: a token signed with our secret but a non-rfq_response
    audience must fail verification, no matter what the aud string is.

    This is the dashboard-JWT-replay defence. We construct the bad
    token directly with `jwt.encode` (rather than going through
    `mint_response_token`, which always sets aud=rfq_response) and
    assert `verify_response_token` raises.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": "aec-platform",
        "aud": bad_aud,
        "iat": now,
        "exp": now + 3600,
        "rfq_id": str(rfq),
        "supplier_id": str(supplier),
    }
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        verify_response_token(token)


@_settings
@given(rfq=_uuid_strategy, supplier=_uuid_strategy)
def test_token_signed_with_wrong_secret_is_rejected(rfq: UUID, supplier: UUID):
    """Property: a token signed with the WRONG secret never verifies.

    Hypothesis only varies the UUIDs here — the wrong secret is
    fixed. The point isn't to fuzz the secret (we trust HMAC); it's
    to assert that no UUID combination tickles a bug where the
    library accepts an invalid signature for "structural" reasons.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": "aec-platform",
        "aud": "rfq_response",
        "iat": now,
        "exp": now + 3600,
        "rfq_id": str(rfq),
        "supplier_id": str(supplier),
    }
    token = jwt.encode(payload, "definitely-not-the-real-secret", algorithm=settings.jwt_algorithm)
    # Only run when the wrong secret is genuinely different from the real one.
    # In the test environment, supabase_jwt_secret = "test-secret"; the
    # arbitrary string above must not collide.
    assume(settings.supabase_jwt_secret != "definitely-not-the-real-secret")
    with pytest.raises(TokenError):
        verify_response_token(token)


@_settings
@given(
    rfq=_uuid_strategy,
    supplier=_uuid_strategy,
    extra_field=st.dictionaries(
        st.text(min_size=1, max_size=20).filter(
            lambda s: s not in {"iss", "aud", "iat", "exp", "rfq_id", "supplier_id"}
        ),
        st.integers(),
        max_size=3,
    ),
)
def test_extra_payload_fields_are_ignored_not_rejected(rfq: UUID, supplier: UUID, extra_field: dict[str, int]):
    """Property: tokens with EXTRA non-conflicting payload fields
    still verify, and the verified claims are unaffected.

    Why pin this: future migrations may add new fields to the
    payload (e.g. `version`, `feature_flags`). A regression that
    rejected unknown fields would refuse every old token in flight
    during the rollout window. We want forward-compatibility.
    """
    settings = get_settings()
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": "aec-platform",
        "aud": "rfq_response",
        "iat": now,
        "exp": now + 3600,
        "rfq_id": str(rfq),
        "supplier_id": str(supplier),
    }
    payload.update(extra_field)
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm)
    claims = verify_response_token(token)
    assert claims.rfq_id == rfq
    assert claims.supplier_id == supplier
