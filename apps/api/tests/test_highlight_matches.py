"""Audit search highlighter (cycle WW1, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/highlight-matches.test.ts`):
  1. Case-insensitive matching.
  2. Non-overlapping (greedy, longer-on-tie wins).
  3. Indexes in original (not lowercased) text.
  4. Empty / null → ().
  5. Cross-language byte-for-byte parity.
"""

from __future__ import annotations

from services.highlight_matches import Match, find_matches

# ---------- Empty inputs ----------


def test_none_text_empty():
    assert find_matches(None, ["foo"]) == ()


def test_empty_text_empty():
    assert find_matches("", ["foo"]) == ()


def test_empty_terms_empty():
    assert find_matches("hello world", []) == ()


# ---------- Single match ----------


def test_match_at_start():
    assert find_matches("hello world", ["hello"]) == (Match(start=0, end=5),)


def test_match_at_end():
    assert find_matches("hello world", ["world"]) == (Match(start=6, end=11),)


def test_no_match_returns_empty():
    assert find_matches("hello world", ["xyz"]) == ()


# ---------- Multiple matches ----------


def test_multiple_terms_in_document_order():
    result = find_matches("hello world", ["hello", "world"])
    assert result == (
        Match(start=0, end=5),
        Match(start=6, end=11),
    )


def test_repeated_occurrences():
    result = find_matches("foo bar foo baz foo", ["foo"])
    assert result == (
        Match(start=0, end=3),
        Match(start=8, end=11),
        Match(start=16, end=19),
    )


def test_terms_in_mixed_input_order():
    """Term order in input doesn't affect result order — output
    is always document order."""
    result = find_matches("alpha beta gamma", ["gamma", "alpha"])
    assert result == (
        Match(start=0, end=5),
        Match(start=11, end=16),
    )


# ---------- Case insensitivity ----------


def test_uppercase_term_matches_lowercase():
    assert find_matches("hello world", ["HELLO"]) == (Match(start=0, end=5),)


def test_mixed_case_text():
    assert find_matches("Hello World", ["hello"]) == (Match(start=0, end=5),)


def test_indexes_refer_to_original_text():
    """Cardinal pin: indexes are positions in the ORIGINAL
    `text`, NOT the lowercased version. Slicing the original
    with the indexes recovers the matched substring."""
    text = "Hello World"
    matches = find_matches(text, ["hello"])
    assert text[matches[0].start : matches[0].end] == "Hello"


# ---------- Overlap resolution ----------


def test_longer_wins_on_tie_at_same_start():
    """`hello` (5 chars) and `ell` (3 chars). Greedy picks
    longer at same start."""
    assert find_matches("hello", ["hello", "ell"]) == (Match(start=0, end=5),)


def test_non_overlapping_repeated():
    """`aaaa` with `aa` → (0,2), then (2,4) (skipping (1,3))."""
    assert find_matches("aaaa", ["aa"]) == (
        Match(start=0, end=2),
        Match(start=2, end=4),
    )


def test_greedy_earlier_wins():
    """`abcabc` with `abc` + `bca` — `abc` at 0 wins; `bca` at 1
    skipped (overlap); `abc` at 3 picked."""
    assert find_matches("abcabc", ["abc", "bca"]) == (
        Match(start=0, end=3),
        Match(start=3, end=6),
    )


# ---------- Whitespace ----------


def test_whitespace_only_term_skipped():
    assert find_matches("hello world", ["   "]) == ()


def test_empty_string_term_skipped():
    assert find_matches("hello", ["", "hello"]) == (Match(start=0, end=5),)


def test_terms_trimmed():
    assert find_matches("hello", ["  hello  "]) == (Match(start=0, end=5),)


# ---------- Unicode ----------


def test_vietnamese_term():
    """Vietnamese term matches Vietnamese text."""
    result = find_matches("123 Lê Lợi, Quận 1", ["Lê Lợi"])
    assert len(result) == 1
    assert result[0].start == 4


# ---------- Frozen ----------


def test_match_is_frozen():
    m = Match(start=0, end=5)
    try:
        m.start = 10  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Match should be frozen")


# ---------- Cross-language ----------


def test_matches_ts_half_canonical_cases():
    """Cross-language pin."""
    cases = [
        ("hello world", ["hello"], (Match(0, 5),)),
        ("hello world", ["world"], (Match(6, 11),)),
        ("hello world", ["hello", "world"], (Match(0, 5), Match(6, 11))),
        ("Hello World", ["hello"], (Match(0, 5),)),
        ("aaaa", ["aa"], (Match(0, 2), Match(2, 4))),
        ("hello", ["hello", "ell"], (Match(0, 5),)),
        ("foo bar foo", ["foo"], (Match(0, 3), Match(8, 11))),
        (None, ["foo"], ()),
        ("", ["foo"], ()),
        ("hello", [], ()),
    ]
    for text, terms, expected in cases:
        assert find_matches(text, terms) == expected, (
            f"find_matches({text!r}, {terms!r}) = {find_matches(text, terms)!r}, expected {expected!r}"
        )
