"""Project code generator (cycle PP2).

Pinned seams:
  1. Format: <PREFIX>-<NNN> with 3-digit zero-padded sequence.
  2. Prefix is uppercased, first 4 alphanumeric chars from
     canonical slug.
  3. Lowest unused sequence (NOT next-after-max).
  4. Sequence starts at 001.
  5. Cap at 999 raises ProjectCodeExhausted.
  6. Empty / unprefix-able org_slug raises ValueError.
  7. Composes with CC3 canonical_slug (BB3 diacritic fold).
"""

from __future__ import annotations

import pytest

from services.project_code import (
    MAX_PROJECT_SEQUENCE,
    PROJECT_PREFIX_LENGTH,
    ProjectCodeExhausted,
    generate_project_code,
)

# ---------- Constants ----------


def test_max_sequence_is_999():
    assert MAX_PROJECT_SEQUENCE == 999


def test_prefix_length_is_4():
    assert PROJECT_PREFIX_LENGTH == 4


# ---------- Empty taken set ----------


def test_first_code_is_001():
    """Pin: sequence starts at 001 (NOT 000)."""
    assert generate_project_code("acme", set()) == "ACME-001"


def test_short_org_slug_yields_short_prefix():
    """Pin: org with < 4 chars gets a shorter prefix."""
    assert generate_project_code("a", set()) == "A-001"
    assert generate_project_code("ab", set()) == "AB-001"


# ---------- Lowest unused ----------


def test_returns_lowest_unused_sequence():
    """Cardinal pin: lowest unused number, NOT next-after-max.
    Defends against deleted-then-recreated holes never getting
    reused."""
    taken = {"ACME-001", "ACME-003"}  # 002 free
    assert generate_project_code("acme", taken) == "ACME-002"


def test_skips_taken_sequences():
    taken = {"ACME-001", "ACME-002", "ACME-003"}
    assert generate_project_code("acme", taken) == "ACME-004"


def test_returns_001_when_002_taken_but_001_free():
    """Holes at the bottom get filled first."""
    assert generate_project_code("acme", {"ACME-002"}) == "ACME-001"


# ---------- Prefix derivation ----------


def test_uppercase_prefix():
    assert generate_project_code("acme", set()) == "ACME-001"
    assert generate_project_code("ACME", set()) == "ACME-001"


def test_strips_hyphens_from_prefix():
    """`my-org` → "MYOR" (4 chars, hyphens removed)."""
    assert generate_project_code("my-org", set()) == "MYOR-001"


def test_truncates_long_prefix_to_4_chars():
    assert generate_project_code("acmecorp", set()) == "ACME-001"


def test_handles_spaces():
    """`acme corp` → canonical_slug → "acme-corp" → strip → "ACMECORP" → first 4 → "ACME"."""
    assert generate_project_code("acme corp", set()) == "ACME-001"


# ---------- Composition with CC3 ----------


def test_vietnamese_diacritics_via_cc3():
    """Cardinal cross-cycle pin: composes with CC3 (which
    composes with BB3 diacritic strip). VN org name → ASCII
    prefix without explicit conversion."""
    # "Hà Nội Co." → canonical_slug → "ha-noi-co" → strip → "HANOICO" → first 4 → "HANO"
    assert generate_project_code("Hà Nội Co.", set()) == "HANO-001"


def test_non_alphanum_chars_collapsed():
    """`acme!@#corp` → canonical → "acme-corp" → "ACMECORP" → "ACME"."""
    assert generate_project_code("acme!@#corp", set()) == "ACME-001"


def test_uppercase_d_with_stroke():
    """`ĐẠI` → canonical → "dai" → "DAI"."""
    assert generate_project_code("Đại", set()) == "DAI-001"


# ---------- Sequence formatting ----------


def test_sequence_zero_padded_to_3_digits():
    """Pin: 3-digit zero-padded. `ACME-001`, NOT `ACME-1`."""
    assert generate_project_code("acme", set()) == "ACME-001"
    assert generate_project_code("acme", {"ACME-001", "ACME-002", "ACME-003", "ACME-004"}) == "ACME-005"


def test_sequence_at_999_boundary():
    """Pin: 999 is valid (3 digits, max sequence)."""
    taken = {f"ACME-{i:03d}" for i in range(1, 999)}
    assert generate_project_code("acme", taken) == "ACME-999"


# ---------- Exhausted ----------


def test_raises_exhausted_when_all_taken():
    """Cardinal pin: cap at 999 → raise. The org should consider
    sub-projects past this point — pin so the limit surfaces
    visibly rather than silently overflowing to 1000."""
    taken = {f"ACME-{i:03d}" for i in range(1, MAX_PROJECT_SEQUENCE + 1)}
    with pytest.raises(ProjectCodeExhausted):
        generate_project_code("acme", taken)


def test_exhausted_message_includes_prefix():
    """Pin exception message includes the prefix for ops debug."""
    taken = {f"ACME-{i:03d}" for i in range(1, MAX_PROJECT_SEQUENCE + 1)}
    with pytest.raises(ProjectCodeExhausted, match="ACME"):
        generate_project_code("acme", taken)


# ---------- Empty / invalid org_slug ----------


def test_empty_slug_raises_value_error():
    with pytest.raises(ValueError):
        generate_project_code("", set())


def test_whitespace_only_slug_raises_value_error():
    with pytest.raises(ValueError):
        generate_project_code("   ", set())


def test_all_punctuation_slug_raises_value_error():
    """`!!!` canonicalizes to empty → ValueError."""
    with pytest.raises(ValueError):
        generate_project_code("!!!", set())


# ---------- Cross-prefix isolation ----------


def test_codes_outside_prefix_ignored():
    """Pin: only codes matching the derived prefix are counted.
    Other prefixes' codes don't affect the sequence."""
    taken = {"OTHER-001", "BETA-005", "FOO-999"}
    # None of these have prefix ACME, so ACME-001 is free.
    assert generate_project_code("acme", taken) == "ACME-001"
