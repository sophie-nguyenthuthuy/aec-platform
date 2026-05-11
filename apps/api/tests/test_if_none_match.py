"""HTTP If-None-Match parser (cycle VV2).

Pinned seams:
  1. Parser identical to LL2 If-Match (delegates).
  2. should_return_304 wildcard logic.
  3. should_return_304 etag-list match by value.
  4. Weak vs strong: same value → match (weak comparison for GET).
  5. Empty header → no precondition.
  6. Cross-cycle: imports LL2's IfMatchList + ETag.
"""

from __future__ import annotations

from services.etag import ETag, IfMatchList, parse_if_match
from services.if_none_match import parse_if_none_match, should_return_304

# ---------- Parser delegates to LL2 ----------


def test_parser_delegates_to_ll2():
    """Cardinal cross-cycle pin: parse_if_none_match returns
    the SAME result as LL2's parse_if_match (parsers identical;
    semantics differ in usage)."""
    cases = [
        None,
        "",
        "*",
        '"abc"',
        'W/"abc"',
        '"a", "b"',
        "garbage",
    ]
    for header in cases:
        ours = parse_if_none_match(header)
        theirs = parse_if_match(header)
        assert ours == theirs, f"parse_if_none_match({header!r}) = {ours!r}, parse_if_match({header!r}) = {theirs!r}"


def test_parse_wildcard():
    result = parse_if_none_match("*")
    assert result == IfMatchList(etags=(), is_wildcard=True)


def test_parse_etag_list():
    result = parse_if_none_match('"a", "b"')
    assert result is not None
    assert len(result.etags) == 2


def test_parse_malformed_returns_none():
    assert parse_if_none_match("garbage") is None


# ---------- should_return_304 — None header ----------


def test_no_header_no_precondition():
    """No If-None-Match → no 304 condition. GET returns
    normal 200."""
    current = ETag(value="abc", weak=False)
    assert should_return_304(None, current) is False


def test_empty_header_returns_no_precondition():
    """Parsed empty header → IfMatchList((), False) → no
    precondition → False."""
    parsed = parse_if_none_match("")
    assert should_return_304(parsed, ETag(value="abc", weak=False)) is False


# ---------- should_return_304 — wildcard ----------


def test_wildcard_with_existing_resource_returns_304():
    """Cardinal pin: `*` wildcard matches any existing resource.
    Used by clients to say "send only if this is new"."""
    parsed = parse_if_none_match("*")
    current = ETag(value="abc", weak=False)
    assert should_return_304(parsed, current) is True


def test_wildcard_with_no_resource_returns_no_304():
    """Wildcard matches existing resource — if there's no
    resource, no match. Caller's GET should 404 separately."""
    parsed = parse_if_none_match("*")
    assert should_return_304(parsed, None) is False


# ---------- should_return_304 — etag list ----------


def test_etag_match_returns_304():
    parsed = parse_if_none_match('"abc"')
    current = ETag(value="abc", weak=False)
    assert should_return_304(parsed, current) is True


def test_etag_no_match_returns_no_304():
    parsed = parse_if_none_match('"xyz"')
    current = ETag(value="abc", weak=False)
    assert should_return_304(parsed, current) is False


def test_etag_match_in_list():
    parsed = parse_if_none_match('"x", "abc", "y"')
    current = ETag(value="abc", weak=False)
    assert should_return_304(parsed, current) is True


def test_etag_match_with_no_current_resource():
    """Resource doesn't exist (current_etag=None) → no match."""
    parsed = parse_if_none_match('"abc"')
    assert should_return_304(parsed, None) is False


# ---------- Weak vs strong comparison ----------


def test_weak_etag_matches_strong_value():
    """Cardinal pin: GET uses weak comparison — weak vs strong
    with same value → match. Per RFC 7232 §3.2."""
    # Client sent W/"abc"; server has strong "abc".
    parsed = parse_if_none_match('W/"abc"')
    current = ETag(value="abc", weak=False)
    assert should_return_304(parsed, current) is True


def test_strong_etag_matches_weak_current():
    """Reverse: client sent strong, server has weak → match."""
    parsed = parse_if_none_match('"abc"')
    current = ETag(value="abc", weak=True)
    assert should_return_304(parsed, current) is True


def test_both_weak_match():
    parsed = parse_if_none_match('W/"abc"')
    current = ETag(value="abc", weak=True)
    assert should_return_304(parsed, current) is True


# ---------- Realistic GET scenarios ----------


def test_get_unchanged_returns_304():
    """Realistic: client cached "v1"; server still has "v1"."""
    parsed = parse_if_none_match('"v1"')
    current = ETag(value="v1", weak=False)
    assert should_return_304(parsed, current) is True


def test_get_changed_returns_no_304():
    """Realistic: client cached "v1"; server now has "v2".
    Should NOT 304 — caller serves the new content."""
    parsed = parse_if_none_match('"v1"')
    current = ETag(value="v2", weak=False)
    assert should_return_304(parsed, current) is False


def test_get_with_multi_etag_one_match():
    """Client has cached versions; if any matches, 304."""
    parsed = parse_if_none_match('"v1", "v2", "v3"')
    current = ETag(value="v2", weak=False)
    assert should_return_304(parsed, current) is True


# ---------- Empty etag list ----------


def test_empty_etag_list_returns_no_304():
    """An IfMatchList with no etags and no wildcard means
    "no precondition" → no 304."""
    empty = IfMatchList(etags=(), is_wildcard=False)
    current = ETag(value="abc", weak=False)
    assert should_return_304(empty, current) is False


# ---------- Cross-cycle composition with LL2 ----------


def test_cross_cycle_uses_ll2_dataclasses():
    """Cardinal cross-cycle pin: `should_return_304` consumes
    LL2's IfMatchList and ETag dataclasses directly."""
    parsed = parse_if_none_match('"abc"')
    assert isinstance(parsed, IfMatchList)
    if parsed is not None:
        for etag in parsed.etags:
            assert isinstance(etag, ETag)
