"""Slugify uniqueness disambiguator (cycle UU1).

Pinned seams:
  1. Base slug returned if not taken.
  2. First collision yields `-2` (NOT `-1`).
  3. Lowest-unused suffix used.
  4. Cap at 999 raises SlugSuffixExhausted.
  5. Empty / unprefix-able name raises ValueError.
  6. Composes with CC3 canonical_slug.
"""

from __future__ import annotations

import pytest

from services.unique_slug import (
    MAX_SLUG_SUFFIX,
    SlugSuffixExhausted,
    unique_slug,
)

# ---------- Constants ----------


def test_max_slug_suffix_is_999():
    assert MAX_SLUG_SUFFIX == 999


# ---------- Base slug ----------


def test_base_returned_if_not_taken():
    assert unique_slug("Acme Corp", set()) == "acme-corp"


def test_base_returned_when_taken_set_unrelated():
    """Other slugs in `taken` don't affect this slug's base."""
    assert unique_slug("Acme Corp", {"other-slug", "another"}) == "acme-corp"


# ---------- Collision suffix ----------


def test_first_collision_yields_dash_2():
    """Cardinal pin: first suffix is `-2`, NOT `-1`. The base
    slug acts as the implicit `-1`."""
    assert unique_slug("Acme Corp", {"acme-corp"}) == "acme-corp-2"


def test_second_collision_yields_dash_3():
    assert unique_slug("Acme", {"acme", "acme-2"}) == "acme-3"


def test_lowest_unused_returned():
    """Cardinal pin: holes get filled. If `acme` and `acme-3` are
    taken (e.g. acme-2 was deleted), return `acme-2`."""
    assert unique_slug("Acme", {"acme", "acme-3"}) == "acme-2"


def test_lowest_unused_with_multiple_holes():
    assert (
        unique_slug(
            "Acme",
            {"acme", "acme-2", "acme-4", "acme-5"},
        )
        == "acme-3"
    )


# ---------- Composes with CC3 ----------


def test_vietnamese_diacritics_via_cc3():
    """Cardinal cross-cycle pin: CC3 (composing BB3) handles
    VN diacritics transparently."""
    assert unique_slug("Hà Nội", set()) == "ha-noi"


def test_vietnamese_collision():
    assert unique_slug("Hà Nội", {"ha-noi"}) == "ha-noi-2"


def test_uppercase_normalized_via_cc3():
    """`ACME CORP` and `acme corp` produce the same slug."""
    assert unique_slug("ACME CORP", set()) == "acme-corp"


def test_special_chars_collapsed_via_cc3():
    """Punctuation collapsed to hyphens."""
    assert unique_slug("Acme & Co.", set()) == "acme-co"


# ---------- Empty / invalid name ----------


def test_empty_name_raises_value_error():
    with pytest.raises(ValueError):
        unique_slug("", set())


def test_whitespace_only_name_raises():
    with pytest.raises(ValueError):
        unique_slug("   ", set())


def test_all_punctuation_raises():
    """`!!!` canonicalizes to empty → ValueError."""
    with pytest.raises(ValueError):
        unique_slug("!!!", set())


# ---------- Exhaustion ----------


def test_raises_exhausted_when_all_taken():
    """Cap pin: `acme` + `acme-2` ... `acme-999` all taken →
    raise."""
    taken = {"acme"}
    taken.update(f"acme-{i}" for i in range(2, MAX_SLUG_SUFFIX + 1))
    with pytest.raises(SlugSuffixExhausted):
        unique_slug("acme", taken)


def test_exhausted_at_max_suffix():
    """At max-1 + base + 999 taken, max is the limit → raise."""
    taken = {"acme"}
    taken.update(f"acme-{i}" for i in range(2, MAX_SLUG_SUFFIX + 1))
    with pytest.raises(SlugSuffixExhausted):
        unique_slug("acme", taken)


def test_exhausted_message_includes_base():
    """Pin error message includes the base slug for ops debug."""
    taken = {"acme"}
    taken.update(f"acme-{i}" for i in range(2, MAX_SLUG_SUFFIX + 1))
    with pytest.raises(SlugSuffixExhausted, match="acme"):
        unique_slug("acme", taken)


def test_below_max_succeeds():
    """All but the very last taken → returns the last."""
    taken = {"acme"}
    taken.update(f"acme-{i}" for i in range(2, MAX_SLUG_SUFFIX))
    assert unique_slug("acme", taken) == f"acme-{MAX_SLUG_SUFFIX}"


# ---------- Realistic scenarios ----------


def test_realistic_org_disambiguation():
    """Two orgs both named "Acme Construction" → second gets `-2`."""
    taken = {"acme-construction"}
    assert unique_slug("Acme Construction", taken) == "acme-construction-2"


def test_realistic_vn_org_collision():
    taken = {"hung-vuong-corp"}
    assert unique_slug("Hùng Vương Corp", taken) == "hung-vuong-corp-2"
