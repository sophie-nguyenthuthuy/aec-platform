"""HTTP Authorization header builder (cycle SS2).

Pinned seams:
  1. Round-trip stable with JJ3 parse_auth_header.
  2. Output capitalized (Bearer, Basic, HMAC-SHA256).
  3. Unknown scheme raises ValueError.
  4. Empty scheme / value raises ValueError.
  5. Composes with JJ3 KNOWN_SCHEMES.
"""

from __future__ import annotations

import pytest

from services.auth_header import AuthHeader, parse_auth_header
from services.auth_header_builder import build_auth_header

# ---------- Capitalization ----------


def test_bearer_capitalized():
    assert build_auth_header("bearer", "abc") == "Bearer abc"


def test_basic_capitalized():
    assert build_auth_header("basic", "dXNlcjpwYXNz") == "Basic dXNlcjpwYXNz"


def test_hmac_sha256_all_caps():
    """Cardinal pin: HMAC-SHA256 uses all-caps for the acronym
    (matches RFC convention for hash algorithm names)."""
    assert build_auth_header("hmac-sha256", "deadbeef") == "HMAC-SHA256 deadbeef"


def test_uppercase_input_normalizes():
    """Input case ignored; output uses canonical capitalization."""
    assert build_auth_header("BEARER", "abc") == "Bearer abc"
    assert build_auth_header("Basic", "x") == "Basic x"


def test_mixed_case_input():
    assert build_auth_header("BeArEr", "abc") == "Bearer abc"
    assert build_auth_header("Hmac-Sha256", "x") == "HMAC-SHA256 x"


# ---------- Value preservation ----------


def test_value_preserved_verbatim():
    """Value is NOT case-normalized — preserve user's value
    exactly. Pin so a refactor that lowercases the value (e.g.
    a Bearer token) doesn't break authentication."""
    assert build_auth_header("bearer", "AbCdEf") == "Bearer AbCdEf"


def test_value_with_special_chars():
    """Value can contain base64 chars (`+`, `/`, `=`)."""
    assert build_auth_header("basic", "dXNlcjpwYXNz=") == "Basic dXNlcjpwYXNz="


# ---------- Validation ----------


def test_empty_scheme_raises():
    with pytest.raises(ValueError):
        build_auth_header("", "abc")


def test_empty_value_raises():
    with pytest.raises(ValueError):
        build_auth_header("bearer", "")


def test_unknown_scheme_raises():
    """Pin: unknown scheme rejects with explicit error rather
    than silently building a malformed header."""
    with pytest.raises(ValueError):
        build_auth_header("digest", "abc")


def test_unknown_scheme_message_lists_known():
    """Pin: error message lists known schemes for ops debug."""
    with pytest.raises(ValueError, match="bearer"):
        build_auth_header("digest", "abc")


# ---------- Round-trip with JJ3 ----------


def test_round_trip_bearer():
    """Cardinal pin: build → parse → build returns same header."""
    built = build_auth_header("bearer", "abc")
    parsed = parse_auth_header(built)
    assert parsed == AuthHeader(scheme="bearer", value="abc")
    rebuilt = build_auth_header(parsed.scheme, parsed.value)
    assert rebuilt == built


def test_round_trip_basic():
    built = build_auth_header("basic", "dXNlcjpwYXNz")
    parsed = parse_auth_header(built)
    assert parsed == AuthHeader(scheme="basic", value="dXNlcjpwYXNz")
    rebuilt = build_auth_header(parsed.scheme, parsed.value)
    assert rebuilt == built


def test_round_trip_hmac_sha256():
    built = build_auth_header("hmac-sha256", "deadbeefcafe123")
    parsed = parse_auth_header(built)
    assert parsed == AuthHeader(scheme="hmac-sha256", value="deadbeefcafe123")
    rebuilt = build_auth_header(parsed.scheme, parsed.value)
    assert rebuilt == built


def test_parse_built_value_preserves_case():
    """Bearer token case is preserved through round-trip."""
    built = build_auth_header("bearer", "AbCdEf123")
    parsed = parse_auth_header(built)
    assert parsed.value == "AbCdEf123"


# ---------- Composition with JJ3 ----------


def test_known_schemes_match_jj3():
    """Cross-cycle pin: builder uses JJ3's KNOWN_SCHEMES set.
    A refactor that diverges would create a build/parse mismatch."""
    from services.auth_header import KNOWN_SCHEMES

    for scheme in KNOWN_SCHEMES:
        # Each known scheme must build successfully.
        result = build_auth_header(scheme, "value")
        assert result, f"build failed for {scheme!r}"
