"""Slug canonicalizer (cycle CC3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/canonical-slug.test.ts`):
  1. MAX_SLUG_LENGTH = 64 (matches API varchar(64)).
  2. VN diacritics stripped (delegates to BB3, including đ → d).
  3. Lowercase.
  4. Non-alphanumeric runs collapsed to single hyphen.
  5. Leading/trailing hyphens trimmed.
  6. Capped at MAX_SLUG_LENGTH; trailing hyphen re-trimmed.
  7. Idempotent: canonical_slug(canonical_slug(x)) == canonical_slug(x).
  8. None / empty / all-non-alphanum → "".
  9. Cross-language byte-for-byte parity with TS half.
"""

from __future__ import annotations

from services.canonical_slug import MAX_SLUG_LENGTH, canonical_slug

# ---------- Constants ----------


def test_max_slug_length_is_64():
    """Pin so a refactor that bumps the API column without
    updating this constant surfaces here (mismatched length
    would cause an API 422 on edge-case long inputs)."""
    assert MAX_SLUG_LENGTH == 64


# ---------- VN inputs ----------


def test_strips_diacritics_from_vn_org_name():
    assert canonical_slug("Hà Nội Construction Co.") == "ha-noi-construction-co"


def test_folds_d_with_stroke_via_bb3_strip():
    assert canonical_slug("Đại Phát Group") == "dai-phat-group"


def test_uppercase_d_with_stroke_folds_to_lowercase_d():
    assert canonical_slug("ĐÔNG ANH") == "dong-anh"


# ---------- Formatting rules ----------


def test_lowercases():
    assert canonical_slug("Foo Bar") == "foo-bar"
    assert canonical_slug("FOOBAR") == "foobar"


def test_collapses_multiple_spaces():
    assert canonical_slug("foo  bar") == "foo-bar"
    assert canonical_slug("foo   bar") == "foo-bar"


def test_collapses_non_alphanumeric_runs():
    assert canonical_slug("foo!@#bar") == "foo-bar"
    assert canonical_slug("foo--bar") == "foo-bar"
    assert canonical_slug("foo___bar") == "foo-bar"


def test_trims_leading_and_trailing_hyphens():
    assert canonical_slug("  foo bar  ") == "foo-bar"
    assert canonical_slug("---foo---") == "foo"
    assert canonical_slug("...foo...") == "foo"


def test_preserves_alphanumeric_chars():
    assert canonical_slug("abc123") == "abc123"
    assert canonical_slug("project-2026") == "project-2026"


def test_handles_apostrophes_as_separator():
    """`Foo's Bar` → `foo-s-bar`. Pin: the apostrophe becomes a
    separator, not silently dropped (which would give `foos-bar`
    — a different and less faithful slug)."""
    assert canonical_slug("Foo's Bar") == "foo-s-bar"


# ---------- Defensive ----------


def test_returns_empty_for_none_and_empty():
    assert canonical_slug(None) == ""
    assert canonical_slug("") == ""


def test_returns_empty_when_strips_to_no_alphanumerics():
    """All-non-alphanumeric input strips to empty. Pin: the
    org-create endpoint can detect this and prompt the user for
    an explicit slug rather than silently storing an empty
    string."""
    assert canonical_slug("!!!") == ""
    assert canonical_slug("---") == ""
    assert canonical_slug("   ") == ""
    assert canonical_slug("...") == ""


# ---------- Length cap ----------


def test_caps_at_max_slug_length():
    long = "a" * 100
    out = canonical_slug(long)
    assert len(out) == MAX_SLUG_LENGTH
    assert out == "a" * MAX_SLUG_LENGTH


def test_trims_trailing_hyphen_when_cap_lands_on_one():
    """A 90-char input with hyphens at every 3rd position, capped
    at 64, may land on a hyphen. Pin: trailing hyphen MUST NOT be
    present after the cap (else the slug looks malformed)."""
    tricky = "ab-" * 30  # 90 chars: "ab-ab-...-ab-"
    out = canonical_slug(tricky)
    assert len(out) <= MAX_SLUG_LENGTH
    assert not out.endswith("-")


def test_does_not_cap_short_input():
    short = "abc-def"
    assert canonical_slug(short) == "abc-def"
    assert len(canonical_slug(short)) == 7


# ---------- Idempotency ----------


def test_idempotent():
    """Applying twice yields the same result. Pin: a refactor
    that double-strips somehow (e.g. re-applies diacritic strip
    on already-ASCII input and breaks something) would surface
    here."""
    cases = [
        "Hà Nội Construction Co.",
        "Foo  Bar",
        "ĐÔNG ANH",
        "foo-bar",
        "abc-123",
        "Foo's Bar",
    ]
    for input_text in cases:
        once = canonical_slug(input_text)
        twice = canonical_slug(once)
        assert twice == once, f"non-idempotent for {input_text!r}: {once!r} → {twice!r}"


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """The Python and TS halves must produce the same output for
    every input. A divergence would silently break slug parity
    between the auto-derivation on the frontend (TS) and the
    server-side validator (Python). Pin via a representative
    input table."""
    cases = [
        ("Hà Nội Construction Co.", "ha-noi-construction-co"),
        ("Đại Phát Group", "dai-phat-group"),
        ("ĐÔNG ANH", "dong-anh"),
        ("Foo Bar", "foo-bar"),
        ("Foo  Bar", "foo-bar"),
        ("Foo's Bar", "foo-s-bar"),
        ("Foo--Bar", "foo-bar"),
        ("---foo---", "foo"),
        ("abc123", "abc123"),
        ("project-2026", "project-2026"),
        ("", ""),
        ("!!!", ""),
    ]
    for input_text, expected in cases:
        assert canonical_slug(input_text) == expected, (
            f"canonical_slug({input_text!r}) = {canonical_slug(input_text)!r}, expected {expected!r}"
        )
