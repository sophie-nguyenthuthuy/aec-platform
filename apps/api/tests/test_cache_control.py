"""HTTP Cache-Control directive parser (cycle NN2).

Pinned seams:
  1. Directive names case-insensitive.
  2. Whitespace tolerated.
  3. max-age non-negative int (negative → None).
  4. Unknown directives IGNORED (forward compat).
  5. Conflicting directives PRESERVED.
  6. None / empty → all-default CacheControl.
"""

from __future__ import annotations

from services.cache_control import CacheControl, parse_cache_control

# ---------- Empty / None ----------


def test_none_returns_default_cache_control():
    result = parse_cache_control(None)
    assert result == CacheControl()
    assert result.max_age is None
    assert result.no_cache is False


def test_empty_returns_default():
    assert parse_cache_control("") == CacheControl()
    assert parse_cache_control("   ") == CacheControl()


# ---------- max-age ----------


def test_max_age_basic():
    result = parse_cache_control("max-age=3600")
    assert result.max_age == 3600


def test_max_age_zero():
    """0 is valid (means "must revalidate immediately")."""
    result = parse_cache_control("max-age=0")
    assert result.max_age == 0


def test_max_age_negative_returns_none():
    """Pin: negative max-age is malformed → field is None.
    Defends against a server returning `max-age=-5` and the
    parser silently treating as zero (or worse, crashing)."""
    result = parse_cache_control("max-age=-5")
    assert result.max_age is None


def test_max_age_non_int_returns_none():
    result = parse_cache_control("max-age=abc")
    assert result.max_age is None


def test_max_age_with_whitespace_around_equals():
    """Pin: `max-age = 3600` (with spaces) parses correctly."""
    result = parse_cache_control("max-age = 3600")
    assert result.max_age == 3600


# ---------- Boolean flags ----------


def test_no_cache():
    result = parse_cache_control("no-cache")
    assert result.no_cache is True
    assert result.no_store is False


def test_no_store():
    result = parse_cache_control("no-store")
    assert result.no_store is True


def test_public():
    result = parse_cache_control("public")
    assert result.public is True


def test_private():
    result = parse_cache_control("private")
    assert result.private is True


def test_must_revalidate():
    result = parse_cache_control("must-revalidate")
    assert result.must_revalidate is True


def test_immutable():
    result = parse_cache_control("immutable")
    assert result.immutable is True


# ---------- s-maxage ----------


def test_s_maxage():
    result = parse_cache_control("s-maxage=600")
    assert result.s_maxage == 600


def test_s_maxage_negative_returns_none():
    result = parse_cache_control("s-maxage=-1")
    assert result.s_maxage is None


# ---------- Combined directives ----------


def test_max_age_and_public():
    result = parse_cache_control("max-age=3600, public")
    assert result.max_age == 3600
    assert result.public is True


def test_no_cache_no_store_combined():
    result = parse_cache_control("no-cache, no-store, must-revalidate")
    assert result.no_cache is True
    assert result.no_store is True
    assert result.must_revalidate is True


def test_max_age_with_immutable():
    """Realistic CDN scenario: long max-age + immutable."""
    result = parse_cache_control("max-age=31536000, public, immutable")
    assert result.max_age == 31536000
    assert result.public is True
    assert result.immutable is True


# ---------- Conflicting directives ----------


def test_no_cache_and_immutable_both_preserved():
    """Cardinal pin: conflicting directives are PRESERVED in the
    result. The parser doesn't pick a winner — caller decides
    precedence based on their cache strategy."""
    result = parse_cache_control("no-cache, immutable")
    assert result.no_cache is True
    assert result.immutable is True


def test_public_and_private_both_preserved():
    """Technically conflicting per RFC, but the parser preserves
    both flags — defensive against server bugs."""
    result = parse_cache_control("public, private")
    assert result.public is True
    assert result.private is True


# ---------- Case insensitivity ----------


def test_directive_case_insensitive():
    """Pin: directive names case-insensitive per RFC 7234."""
    result = parse_cache_control("Max-Age=3600")
    assert result.max_age == 3600


def test_flag_case_insensitive():
    result = parse_cache_control("NO-CACHE")
    assert result.no_cache is True


def test_mixed_case_directives():
    result = parse_cache_control("Max-Age=3600, No-Store, Public")
    assert result.max_age == 3600
    assert result.no_store is True
    assert result.public is True


# ---------- Whitespace tolerance ----------


def test_extra_whitespace_between_directives():
    result = parse_cache_control("  max-age=3600  ,  public  ")
    assert result.max_age == 3600
    assert result.public is True


def test_no_space_after_comma():
    result = parse_cache_control("max-age=3600,public")
    assert result.max_age == 3600
    assert result.public is True


def test_empty_directive_segments_skipped():
    """Empty segments between commas (`a,,b`) are skipped."""
    result = parse_cache_control("max-age=3600,,public")
    assert result.max_age == 3600
    assert result.public is True


# ---------- Unknown directives (forward compat) ----------


def test_unknown_flag_ignored():
    """Cardinal pin: unknown directives don't crash. Pin so a
    refactor that errors on unknown surfaces here — defends
    against future RFC additions breaking the parser."""
    result = parse_cache_control("future-directive")
    assert result == CacheControl()


def test_unknown_value_directive_ignored():
    result = parse_cache_control("future-key=42")
    assert result == CacheControl()


def test_unknown_alongside_known_preserves_known():
    result = parse_cache_control("max-age=3600, future-thing")
    assert result.max_age == 3600


# ---------- Frozen ----------


def test_cache_control_is_frozen():
    cc = CacheControl(max_age=3600)
    try:
        cc.max_age = 100  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("CacheControl should be frozen")
