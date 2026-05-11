"""HMAC timing-safe compare wrapper (cycle UU3).

Pinned seams:
  1. Equal valid inputs -> True.
  2. None either side -> False.
  3. Empty either side -> False.
  4. Type mismatch (str vs bytes) -> False (no auto-convert).
  5. Length mismatch within same type -> False.
  6. No exceptions for any combination.
"""

from __future__ import annotations

from services.hmac_compare import safe_compare

# ---------- Equal ----------


def test_equal_strings():
    assert safe_compare("abc", "abc") is True


def test_equal_bytes():
    assert safe_compare(b"abc", b"abc") is True


def test_equal_long_strings():
    """Pin: equal long inputs (typical SHA-256 hex digests)
    return True."""
    a = "deadbeef" * 8  # 64 chars
    b = "deadbeef" * 8
    assert safe_compare(a, b) is True


def test_equal_unicode():
    assert safe_compare("Hà Nội", "Hà Nội") is True


# ---------- Different ----------


def test_different_strings():
    assert safe_compare("abc", "abd") is False


def test_different_bytes():
    assert safe_compare(b"abc", b"abd") is False


def test_length_mismatch_same_type():
    """Pin: hmac.compare_digest handles length mismatch
    without raising. Wrapper returns False."""
    assert safe_compare("abc", "abcd") is False
    assert safe_compare("abcd", "abc") is False
    assert safe_compare(b"abc", b"abcd") is False


# ---------- None ----------


def test_none_left_returns_false():
    """Cardinal pin: None either side -> False, no raise."""
    assert safe_compare(None, "abc") is False


def test_none_right_returns_false():
    assert safe_compare("abc", None) is False


def test_none_both_returns_false():
    assert safe_compare(None, None) is False


# ---------- Empty ----------


def test_empty_string_both_returns_false():
    """Cardinal pin: empty either side -> False (NOT True even
    if both are empty -- empty isn't a meaningful signature).
    Defends against a refactor that returns True for `"" == ""`
    silently passing auth."""
    assert safe_compare("", "") is False


def test_empty_string_left_returns_false():
    assert safe_compare("", "abc") is False


def test_empty_string_right_returns_false():
    assert safe_compare("abc", "") is False


def test_empty_bytes_both_returns_false():
    assert safe_compare(b"", b"") is False


def test_empty_bytes_one_side_returns_false():
    assert safe_compare(b"", b"abc") is False
    assert safe_compare(b"abc", b"") is False


# ---------- Type mismatch ----------


def test_str_vs_bytes_returns_false():
    """Cardinal pin: type mismatch -> False, NO auto-convert.
    `b"abc" == "abc"` would be False in Python anyway, but
    `hmac.compare_digest(b"abc", "abc")` RAISES TypeError --
    pin so we don't surface the raise as 500."""
    assert safe_compare("abc", b"abc") is False
    assert safe_compare(b"abc", "abc") is False


def test_str_vs_bytes_no_raise():
    """Pin no raise for mixed types -- auth-failed (False) is
    the right surface, not a 500."""
    safe_compare("abc", b"abc")  # no raise
    safe_compare(b"abc", "abc")  # no raise


# ---------- Realistic signature compare ----------


def test_realistic_sha256_hex_match():
    """Pin: typical SHA-256 hex digest comparison."""
    sig_a = "a" * 64
    sig_b = "a" * 64
    assert safe_compare(sig_a, sig_b) is True


def test_realistic_sha256_hex_mismatch():
    sig_a = "a" * 64
    sig_b = "a" * 63 + "b"
    assert safe_compare(sig_a, sig_b) is False


# ---------- No exceptions ----------


def test_no_exceptions_for_any_combination():
    """Pin: every combination of None/empty/type-mismatch
    returns a bool, never raises."""
    cases = [
        (None, None),
        (None, "abc"),
        ("abc", None),
        ("", ""),
        ("", "abc"),
        ("abc", ""),
        (b"", b""),
        ("abc", b"abc"),
        (b"abc", "abc"),
        ("abc", "abc"),
        (b"abc", b"abc"),
    ]
    for a, b in cases:
        result = safe_compare(a, b)
        assert isinstance(result, bool), f"safe_compare({a!r}, {b!r}) = {result!r}"
