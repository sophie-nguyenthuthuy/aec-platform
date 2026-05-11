"""HTTP Authorization header parser (cycle JJ3).

Pinned seams:
  1. KNOWN_SCHEMES = {bearer, basic, hmac-sha256}.
  2. Scheme detection case-insensitive; output lowercased.
  3. Value preserved verbatim (no decoding).
  4. Empty value → None.
  5. Unknown scheme → None.
  6. None / empty → None.
  7. Multiple whitespace between scheme/value tolerated.
  8. AuthHeader is frozen.
"""

from __future__ import annotations

from services.auth_header import (
    KNOWN_SCHEMES,
    AuthHeader,
    parse_auth_header,
)

# ---------- Constants ----------


def test_known_schemes_canonical_set():
    """Pin: 3 known schemes. Adding a 4th requires updating both
    the parser and downstream auth gates — pin so a sneaky add
    doesn't slip past."""
    assert frozenset({"bearer", "basic", "hmac-sha256"}) == KNOWN_SCHEMES


def test_known_schemes_is_frozen():
    assert isinstance(KNOWN_SCHEMES, frozenset)


def test_known_schemes_are_lowercased():
    """Pin: schemes stored lowercase; case-insensitive comparison
    happens via .lower() in the parser."""
    for scheme in KNOWN_SCHEMES:
        assert scheme == scheme.lower()


# ---------- Bearer ----------


def test_parse_bearer():
    assert parse_auth_header("Bearer abc123") == AuthHeader(scheme="bearer", value="abc123")


def test_parse_bearer_uppercase_scheme():
    """Pin case-insensitive scheme detection. Output is always
    lowercased canonical."""
    assert parse_auth_header("BEARER abc") == AuthHeader(scheme="bearer", value="abc")
    assert parse_auth_header("Bearer abc") == AuthHeader(scheme="bearer", value="abc")
    assert parse_auth_header("bearer abc") == AuthHeader(scheme="bearer", value="abc")


def test_parse_bearer_token_preserves_case_in_value():
    """Pin: VALUE is preserved verbatim. Bearer tokens are
    case-sensitive."""
    assert parse_auth_header("Bearer AbCdEf123").value == "AbCdEf123"


# ---------- Basic ----------


def test_parse_basic():
    """Basic auth value is base64-encoded `user:pass`. Parser
    does NOT decode — caller's job."""
    encoded = "dXNlcjpwYXNz"  # b64("user:pass")
    assert parse_auth_header(f"Basic {encoded}") == AuthHeader(scheme="basic", value=encoded)


def test_parse_basic_value_preserved_verbatim():
    """Cardinal pin: NO decoding. The raw base64 string passes
    through unchanged so the caller can call b64decode() (and
    handle errors) explicitly."""
    encoded = "dXNlcjpwYXNz="
    result = parse_auth_header(f"Basic {encoded}")
    assert result is not None
    assert result.value == encoded


# ---------- HMAC-SHA256 ----------


def test_parse_hmac_sha256():
    sig = "deadbeefcafe123"
    assert parse_auth_header(f"HMAC-SHA256 {sig}") == AuthHeader(scheme="hmac-sha256", value=sig)


def test_parse_hmac_case_insensitive():
    sig = "deadbeef"
    assert parse_auth_header(f"hmac-sha256 {sig}").scheme == "hmac-sha256"
    assert parse_auth_header(f"Hmac-Sha256 {sig}").scheme == "hmac-sha256"
    assert parse_auth_header(f"HMAC-SHA256 {sig}").scheme == "hmac-sha256"


# ---------- Unknown scheme ----------


def test_unknown_scheme_returns_none():
    """Cardinal pin: unknown schemes reject with None. Defends
    against a refactor that accepts arbitrary schemes downstream
    (HTTP 401 surfaces explicitly rather than silent pass-through)."""
    assert parse_auth_header("Digest abc") is None
    assert parse_auth_header("OAuth abc") is None
    assert parse_auth_header("Custom abc") is None


# ---------- Whitespace handling ----------


def test_multi_space_between_scheme_and_value_tolerated():
    """split(None, 1) collapses whitespace runs."""
    assert parse_auth_header("Bearer    abc") == AuthHeader(scheme="bearer", value="abc")


def test_tab_separator_tolerated():
    assert parse_auth_header("Bearer\tabc") == AuthHeader(scheme="bearer", value="abc")


def test_boundary_whitespace_stripped():
    assert parse_auth_header("  Bearer abc  ") == AuthHeader(scheme="bearer", value="abc")


# ---------- Empty / malformed ----------


def test_none_returns_none():
    assert parse_auth_header(None) is None


def test_empty_returns_none():
    assert parse_auth_header("") is None


def test_whitespace_only_returns_none():
    assert parse_auth_header("   ") is None


def test_scheme_only_no_value_returns_none():
    """Pin: scheme alone (no value) → None. A bare `Bearer` is
    a client bug worth surfacing as 401 rather than silently
    pass-through."""
    assert parse_auth_header("Bearer") is None


def test_scheme_with_trailing_space_only_returns_none():
    """`Bearer ` (with trailing space, no value) → None after
    boundary strip + split."""
    assert parse_auth_header("Bearer ") is None


def test_no_scheme_separator_returns_none():
    """`BearerNoSpace` — no whitespace separator → can't parse."""
    assert parse_auth_header("BearerNoSpace") is None


# ---------- Value can contain spaces ----------


def test_value_with_internal_spaces_preserved():
    """Multi-word values pass through as a single value string.
    Bearer tokens technically shouldn't have spaces, but this is
    structural parsing — caller can validate format."""
    result = parse_auth_header("Bearer abc def")
    assert result == AuthHeader(scheme="bearer", value="abc def")


# ---------- AuthHeader shape ----------


def test_auth_header_is_frozen():
    h = AuthHeader(scheme="bearer", value="abc")
    try:
        h.scheme = "basic"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("AuthHeader should be frozen")
