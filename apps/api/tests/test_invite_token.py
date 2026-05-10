"""Project member invite token validator (cycle AAA1).

Pinned seams:
  1. Round-trip: build → parse returns same payload.
  2. Tampered signature → None.
  3. Expired token → None.
  4. Malformed → None.
  5. MAX_INVITE_VALIDITY_DAYS enforced.
  6. Composes UU3 + GG3 + YY2 + PP3 + RR2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.invite_token import (
    MAX_INVITE_VALIDITY_DAYS,
    InvitePayload,
    build_invite_token,
    parse_invite_token,
)

SECRET = "test-secret-key"
NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


def _payload(
    org_id: str = "acme",
    email: str = "user@example.com",
    days_valid: int = 7,
) -> InvitePayload:
    return InvitePayload(
        org_id=org_id,
        invitee_email=email,
        expires_at=NOW + timedelta(days=days_valid),
    )


# ---------- Constants ----------


def test_max_validity_30_days():
    assert MAX_INVITE_VALIDITY_DAYS == 30


# ---------- Round-trip ----------


def test_build_parse_round_trip():
    payload = _payload()
    token = build_invite_token(payload, SECRET, NOW)
    parsed = parse_invite_token(token, SECRET, NOW)
    assert parsed == payload


def test_round_trip_preserves_org_id():
    payload = _payload(org_id="vingroup-vn")
    token = build_invite_token(payload, SECRET, NOW)
    parsed = parse_invite_token(token, SECRET, NOW)
    assert parsed is not None
    assert parsed.org_id == "vingroup-vn"


def test_round_trip_preserves_email():
    payload = _payload(email="invitee@vingroup.com.vn")
    token = build_invite_token(payload, SECRET, NOW)
    parsed = parse_invite_token(token, SECRET, NOW)
    assert parsed is not None
    assert parsed.invitee_email == "invitee@vingroup.com.vn"


def test_token_format():
    """Token = `<base64>.<hex_signature>`."""
    token = build_invite_token(_payload(), SECRET, NOW)
    assert "." in token
    payload_part, sig = token.rpartition(".")[0], token.rpartition(".")[2]
    assert payload_part != ""
    assert sig != ""
    # Signature is hex.
    assert all(c in "0123456789abcdef" for c in sig)


def test_token_no_padding():
    """Pin: base64url payload has no `=` padding."""
    token = build_invite_token(_payload(), SECRET, NOW)
    payload_part = token.rpartition(".")[0]
    assert "=" not in payload_part


# ---------- Build validation ----------


def test_build_empty_secret_raises():
    with pytest.raises(ValueError):
        build_invite_token(_payload(), "", NOW)


def test_build_empty_org_id_raises():
    payload = InvitePayload(
        org_id="",
        invitee_email="user@example.com",
        expires_at=NOW + timedelta(days=7),
    )
    with pytest.raises(ValueError):
        build_invite_token(payload, SECRET, NOW)


def test_build_invalid_email_raises():
    """Cardinal pin: GG3 composition. Invalid email rejected."""
    payload = InvitePayload(
        org_id="acme",
        invitee_email="not-an-email",
        expires_at=NOW + timedelta(days=7),
    )
    with pytest.raises(ValueError):
        build_invite_token(payload, SECRET, NOW)


def test_build_past_expiry_raises():
    payload = InvitePayload(
        org_id="acme",
        invitee_email="user@example.com",
        expires_at=NOW - timedelta(hours=1),
    )
    with pytest.raises(ValueError):
        build_invite_token(payload, SECRET, NOW)


def test_build_now_expiry_raises():
    """expires_at == now is also rejected (must be strictly future)."""
    payload = InvitePayload(
        org_id="acme",
        invitee_email="user@example.com",
        expires_at=NOW,
    )
    with pytest.raises(ValueError):
        build_invite_token(payload, SECRET, NOW)


def test_build_beyond_max_validity_raises():
    """Cardinal pin: expires_at > now + MAX_INVITE_VALIDITY_DAYS rejects."""
    payload = InvitePayload(
        org_id="acme",
        invitee_email="user@example.com",
        expires_at=NOW + timedelta(days=MAX_INVITE_VALIDITY_DAYS + 1),
    )
    with pytest.raises(ValueError):
        build_invite_token(payload, SECRET, NOW)


def test_build_at_max_validity_succeeds():
    """At exactly the cap is fine."""
    payload = InvitePayload(
        org_id="acme",
        invitee_email="user@example.com",
        expires_at=NOW + timedelta(days=MAX_INVITE_VALIDITY_DAYS),
    )
    token = build_invite_token(payload, SECRET, NOW)
    assert token


# ---------- Parse — invalid ----------


def test_parse_none_returns_none():
    assert parse_invite_token(None, SECRET, NOW) is None


def test_parse_empty_returns_none():
    assert parse_invite_token("", SECRET, NOW) is None


def test_parse_no_dot_returns_none():
    assert parse_invite_token("no-dot-here", SECRET, NOW) is None


def test_parse_no_secret_returns_none():
    token = build_invite_token(_payload(), SECRET, NOW)
    assert parse_invite_token(token, "", NOW) is None


def test_parse_malformed_base64_returns_none():
    assert parse_invite_token("not-base64!.sig", SECRET, NOW) is None


def test_parse_malformed_canonical_returns_none():
    """Valid base64 of non-canonical-query content."""
    import base64

    bogus = base64.urlsafe_b64encode(b"not a query").rstrip(b"=").decode("ascii")
    token = f"{bogus}.fakesig"
    assert parse_invite_token(token, SECRET, NOW) is None


def test_parse_missing_fields_returns_none():
    """Canonical query that's missing org_id/email/expires_at."""
    import base64

    canonical = "org_id=acme"  # missing email + expires_at
    payload_b64 = base64.urlsafe_b64encode(canonical.encode()).rstrip(b"=").decode("ascii")
    token = f"{payload_b64}.fakesig"
    assert parse_invite_token(token, SECRET, NOW) is None


# ---------- Tamper detection ----------


def test_tampered_signature_returns_none():
    """Cardinal pin: signature mismatch → None (not exception).
    Constant-time compare via UU3."""
    token = build_invite_token(_payload(), SECRET, NOW)
    payload_part, sig = token.rpartition(".")[0], token.rpartition(".")[2]
    # Flip last char of signature.
    tampered_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    tampered_token = f"{payload_part}.{tampered_sig}"
    assert parse_invite_token(tampered_token, SECRET, NOW) is None


def test_tampered_payload_returns_none():
    """Tampered payload → signature mismatch → None."""
    import base64

    token = build_invite_token(_payload(org_id="acme"), SECRET, NOW)
    sig = token.rpartition(".")[2]

    # Replace payload with one for a different org.
    tampered_canonical = "email=user%40example.com&expires_at=2026-05-17T12%3A00%3A00%2B00%3A00&org_id=evil"
    tampered_payload = base64.urlsafe_b64encode(tampered_canonical.encode()).rstrip(b"=").decode("ascii")
    tampered_token = f"{tampered_payload}.{sig}"
    assert parse_invite_token(tampered_token, SECRET, NOW) is None


def test_wrong_secret_returns_none():
    """Different secret → signature doesn't verify → None."""
    token = build_invite_token(_payload(), SECRET, NOW)
    assert parse_invite_token(token, "different-secret", NOW) is None


# ---------- Expiry ----------


def test_expired_token_returns_none():
    """Cardinal pin: expired token rejected even with valid signature."""
    payload = _payload(days_valid=1)
    token = build_invite_token(payload, SECRET, NOW)
    later = NOW + timedelta(days=2)
    assert parse_invite_token(token, SECRET, later) is None


def test_token_at_exact_expiry_returns_none():
    """At expires_at == now, token is expired (strict `>=` boundary)."""
    payload = _payload(days_valid=1)
    token = build_invite_token(payload, SECRET, NOW)
    at_expiry = NOW + timedelta(days=1)
    assert parse_invite_token(token, SECRET, at_expiry) is None


def test_token_just_before_expiry_valid():
    payload = _payload(days_valid=1)
    token = build_invite_token(payload, SECRET, NOW)
    just_before = NOW + timedelta(days=1, microseconds=-1)
    parsed = parse_invite_token(token, SECRET, just_before)
    assert parsed is not None


# ---------- Cross-cycle composition ----------


def test_composes_uu3_safe_compare():
    """Cross-cycle pin: signature compare uses UU3 safe_compare
    (constant-time). Tampered byte-by-byte should still reject."""
    token = build_invite_token(_payload(), SECRET, NOW)
    sig = token.rpartition(".")[2]
    payload_b64 = token.rpartition(".")[0]

    # Flip each byte of signature; all should reject.
    for i in range(len(sig)):
        ch = sig[i]
        flipped = "0" if ch != "0" else "1"
        tampered = sig[:i] + flipped + sig[i + 1 :]
        result = parse_invite_token(
            f"{payload_b64}.{tampered}",
            SECRET,
            NOW,
        )
        assert result is None, f"flip at {i} should reject"


def test_composes_gg3_email_validation():
    """Cross-cycle pin: invalid emails rejected at build time."""
    invalid_emails = [
        "no-at-sign",
        "@no-local.com",
        "user@",
        ".leading-dot@example.com",
    ]
    for email in invalid_emails:
        with pytest.raises(ValueError):
            build_invite_token(
                InvitePayload(
                    org_id="acme",
                    invitee_email=email,
                    expires_at=NOW + timedelta(days=1),
                ),
                SECRET,
                NOW,
            )


def test_composes_yy2_iso_round_trip():
    """Cross-cycle pin: expires_at preserved across YY2 ISO encode/decode.
    Microseconds should round-trip too."""
    payload = InvitePayload(
        org_id="acme",
        invitee_email="user@example.com",
        expires_at=datetime(
            2026,
            5,
            17,
            12,
            0,
            0,
            123456,
            tzinfo=UTC,
        ),
    )
    token = build_invite_token(payload, SECRET, NOW)
    parsed = parse_invite_token(token, SECRET, NOW)
    assert parsed is not None
    assert parsed.expires_at == payload.expires_at


def test_composes_pp3_canonical_query_deterministic():
    """Cross-cycle pin: same payload → same token (PP3 deterministic)."""
    payload = _payload()
    token1 = build_invite_token(payload, SECRET, NOW)
    token2 = build_invite_token(payload, SECRET, NOW)
    assert token1 == token2


# ---------- Frozen ----------


def test_invite_payload_is_frozen():
    p = _payload()
    try:
        p.org_id = "other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("InvitePayload should be frozen")
