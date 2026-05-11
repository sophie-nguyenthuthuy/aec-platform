"""HTTP ETag / If-Match parser (cycle LL2).

Pinned seams:
  1. Strong: `"value"`.
  2. Weak: `W/"value"` (prefix detected, value unquoted).
  3. `*` wildcard exclusive (mixed → None).
  4. Comma-separated list with whitespace tolerance.
  5. None / empty If-Match → IfMatchList((), False).
  6. Malformed → None.
"""

from __future__ import annotations

from services.etag import ETag, IfMatchList, parse_etag, parse_if_match

# ---------- parse_etag ----------


def test_parse_strong_etag():
    assert parse_etag('"abc"') == ETag(value="abc", weak=False)


def test_parse_weak_etag():
    """Cardinal pin: W/ prefix sets weak=True; value strips W/."""
    assert parse_etag('W/"abc"') == ETag(value="abc", weak=True)


def test_parse_etag_with_whitespace_strip():
    assert parse_etag('  "abc"  ') == ETag(value="abc", weak=False)


def test_parse_etag_empty_value_valid():
    """`""` (empty quoted string) is structurally valid."""
    assert parse_etag('""') == ETag(value="", weak=False)


def test_parse_etag_unquoted_returns_none():
    assert parse_etag("abc") is None


def test_parse_etag_unclosed_quote_returns_none():
    assert parse_etag('"abc') is None


def test_parse_etag_only_weak_prefix_returns_none():
    """`W/` without a value is invalid."""
    assert parse_etag("W/") is None


def test_parse_etag_none_and_empty():
    assert parse_etag(None) is None
    assert parse_etag("") is None
    assert parse_etag("   ") is None


def test_parse_etag_value_with_special_chars():
    """Value can contain non-quote characters."""
    assert parse_etag('"abc-def_123"') == ETag(value="abc-def_123", weak=False)


# ---------- parse_if_match — empty / wildcard ----------


def test_if_match_none_returns_no_precondition():
    """None header → empty list, NOT wildcard. Pin so the
    distinction between "no header" and "match anything" is
    surfaced explicitly."""
    result = parse_if_match(None)
    assert result == IfMatchList(etags=(), is_wildcard=False)


def test_if_match_empty_returns_no_precondition():
    assert parse_if_match("") == IfMatchList(etags=(), is_wildcard=False)
    assert parse_if_match("   ") == IfMatchList(etags=(), is_wildcard=False)


def test_if_match_wildcard():
    result = parse_if_match("*")
    assert result == IfMatchList(etags=(), is_wildcard=True)


def test_if_match_wildcard_with_whitespace():
    assert parse_if_match("  *  ") == IfMatchList(etags=(), is_wildcard=True)


# ---------- parse_if_match — single entry ----------


def test_if_match_single_strong():
    result = parse_if_match('"abc"')
    assert result is not None
    assert result.etags == (ETag(value="abc", weak=False),)
    assert result.is_wildcard is False


def test_if_match_single_weak():
    result = parse_if_match('W/"abc"')
    assert result is not None
    assert result.etags == (ETag(value="abc", weak=True),)


# ---------- parse_if_match — list ----------


def test_if_match_multiple_strong():
    result = parse_if_match('"a", "b", "c"')
    assert result is not None
    assert result.etags == (
        ETag(value="a", weak=False),
        ETag(value="b", weak=False),
        ETag(value="c", weak=False),
    )


def test_if_match_mixed_strong_and_weak():
    result = parse_if_match('"a", W/"b", "c"')
    assert result is not None
    assert result.etags == (
        ETag(value="a", weak=False),
        ETag(value="b", weak=True),
        ETag(value="c", weak=False),
    )


def test_if_match_whitespace_tolerated_in_list():
    """Pin: extra whitespace between entries doesn't break parsing."""
    result = parse_if_match('  "a"  ,  "b"  ')
    assert result is not None
    assert len(result.etags) == 2


def test_if_match_no_space_after_comma():
    """RFC 7232 OWS — both `, ` and `,` valid."""
    result = parse_if_match('"a","b"')
    assert result is not None
    assert len(result.etags) == 2


# ---------- parse_if_match — invalid ----------


def test_if_match_mixed_wildcard_returns_none():
    """Cardinal pin: `*` cannot be mixed with other entries.
    A refactor that accepts `"a", *` would silently bypass the
    optimistic-concurrency check for half the conditions."""
    assert parse_if_match('"a", *') is None
    assert parse_if_match('*, "a"') is None


def test_if_match_malformed_entry_returns_none():
    """Any malformed entry invalidates the whole header. Pin so
    a refactor that silently skips bad entries surfaces here —
    optimistic concurrency requires ALL conditions to apply."""
    assert parse_if_match('"a", garbage') is None
    assert parse_if_match('garbage, "a"') is None
    assert parse_if_match('"a", "unclosed') is None


def test_if_match_only_garbage_returns_none():
    assert parse_if_match("garbage") is None
    assert parse_if_match('"a"x') is None


# ---------- Frozen invariants ----------


def test_etag_is_frozen():
    e = ETag(value="abc", weak=False)
    try:
        e.value = "xyz"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ETag should be frozen")


def test_if_match_list_is_frozen():
    lst = IfMatchList(etags=(), is_wildcard=False)
    try:
        lst.is_wildcard = True  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("IfMatchList should be frozen")
