"""Estimate quantity unit normalizer (cycle MM2).

Pinned seams:
  1. 1 tấn = 1000 kg (VN metric, NOT US ton).
  2. 1 tạ = 100 kg.
  3. Different dimensions don't auto-convert.
  4. Count units don't inter-convert (different counts → None).
  5. Same-unit identity always succeeds.
  6. Diacritic-stripped aliases (tan → tấn) via BB3 composition.
"""

from __future__ import annotations

from services.qty_unit import (
    UNITS,
    convert_qty,
    parse_unit,
    unit_dimension,
)

# ---------- UNITS registry ----------


def test_units_count():
    """5 weight + 4 length + 2 area + 2 volume + 6 count = 19."""
    assert len(UNITS) == 19


def test_units_is_frozen():
    assert isinstance(UNITS, frozenset)


def test_units_includes_canonical_weight():
    for u in ["kg", "tấn", "tạ", "lạng"]:
        assert u in UNITS


def test_units_includes_count_units():
    for u in ["hộp", "bộ", "cái", "chiếc", "viên", "tấm"]:
        assert u in UNITS


# ---------- parse_unit ----------


def test_parse_canonical_kg():
    assert parse_unit("kg") == "kg"


def test_parse_canonical_with_diacritics():
    assert parse_unit("tấn") == "tấn"
    assert parse_unit("hộp") == "hộp"


def test_parse_uppercase_normalizes_to_lower():
    assert parse_unit("KG") == "kg"
    assert parse_unit("Kg ") == "kg"


def test_parse_ascii_alias_via_diacritic_strip():
    """Cardinal pin: BB3 composition. ASCII-typed input
    (without diacritics) normalizes to canonical Vietnamese."""
    assert parse_unit("tan") == "tấn"
    assert parse_unit("TAN") == "tấn"
    assert parse_unit("ta") == "tạ"
    assert parse_unit("hop") == "hộp"


def test_parse_m_squared_via_alias():
    """`m2` typed input normalizes to `m²`."""
    assert parse_unit("m2") == "m²"
    assert parse_unit("M2") == "m²"


def test_parse_m_cubed_via_alias():
    assert parse_unit("m3") == "m³"


def test_parse_unknown_returns_none():
    assert parse_unit("tonne") is None
    assert parse_unit("foo") is None
    assert parse_unit("invalid") is None


def test_parse_none_and_empty():
    assert parse_unit(None) is None
    assert parse_unit("") is None
    assert parse_unit("   ") is None


# ---------- unit_dimension ----------


def test_dimension_weight():
    assert unit_dimension("kg") == "weight"
    assert unit_dimension("tấn") == "weight"
    assert unit_dimension("tạ") == "weight"


def test_dimension_length():
    assert unit_dimension("m") == "length"
    assert unit_dimension("km") == "length"
    assert unit_dimension("mm") == "length"


def test_dimension_area():
    assert unit_dimension("m²") == "area"
    assert unit_dimension("cm²") == "area"


def test_dimension_volume():
    assert unit_dimension("m³") == "volume"
    assert unit_dimension("lít") == "volume"


def test_dimension_count():
    assert unit_dimension("hộp") == "count"
    assert unit_dimension("bộ") == "count"
    assert unit_dimension("cái") == "count"


def test_dimension_through_alias():
    """Aliases resolve through to canonical, so dimension lookup
    works."""
    assert unit_dimension("tan") == "weight"
    assert unit_dimension("m2") == "area"
    assert unit_dimension("hop") == "count"


def test_dimension_unknown_returns_none():
    assert unit_dimension("foo") is None
    assert unit_dimension(None) is None


# ---------- convert_qty — weight ----------


def test_convert_tan_to_kg():
    """Cardinal pin: 1 tấn = 1000 kg (Vietnamese metric).
    A refactor to US ton (907 kg) would silently shift every
    weight conversion."""
    assert convert_qty(1, "tấn", "kg") == 1000.0


def test_convert_kg_to_tan():
    assert convert_qty(1500, "kg", "tấn") == 1.5


def test_convert_ta_to_kg():
    """1 tạ = 100 kg."""
    assert convert_qty(1, "tạ", "kg") == 100.0


def test_convert_lang_to_kg():
    """1 lạng = 100g = 0.1 kg."""
    assert convert_qty(1, "lạng", "kg") == 0.1


def test_convert_via_ascii_alias():
    """Aliases work in conversion too."""
    assert convert_qty(1, "tan", "kg") == 1000.0


# ---------- convert_qty — length ----------


def test_convert_m_to_km():
    assert convert_qty(1500, "m", "km") == 1.5


def test_convert_mm_to_m():
    assert convert_qty(1000, "mm", "m") == 1.0


def test_convert_cm_to_m():
    assert convert_qty(100, "cm", "m") == 1.0


# ---------- convert_qty — area ----------


def test_convert_cm2_to_m2():
    """1 m² = 10,000 cm²."""
    assert convert_qty(10000, "cm²", "m²") == 1.0


# ---------- convert_qty — same unit identity ----------


def test_same_unit_identity():
    """Same-unit always returns input qty as float."""
    assert convert_qty(5, "kg", "kg") == 5.0
    assert convert_qty(5, "hộp", "hộp") == 5.0
    assert convert_qty(5.5, "m³", "m³") == 5.5


def test_same_unit_identity_via_alias():
    """`tan → tấn` is the same canonical unit, so identity."""
    assert convert_qty(5, "tan", "tấn") == 5.0


# ---------- convert_qty — different dimensions ----------


def test_different_dimensions_returns_none():
    """m³ to m² are different dimensions — no auto-conversion."""
    assert convert_qty(1, "m³", "m²") is None
    assert convert_qty(1, "kg", "m") is None
    assert convert_qty(1, "hộp", "kg") is None


# ---------- convert_qty — count units ----------


def test_count_to_count_different_returns_none():
    """Cardinal pin: distinct count units don't inter-convert.
    1 hộp ≠ 1 bộ — they're operationally different objects."""
    assert convert_qty(5, "hộp", "bộ") is None
    assert convert_qty(5, "cái", "chiếc") is None
    assert convert_qty(5, "viên", "tấm") is None


def test_count_to_count_same_unit_succeeds():
    """Same-unit identity overrides the count-no-convert rule."""
    assert convert_qty(5, "hộp", "hộp") == 5.0


# ---------- convert_qty — unknown units ----------


def test_unknown_unit_returns_none():
    assert convert_qty(5, "foo", "kg") is None
    assert convert_qty(5, "kg", "foo") is None
    assert convert_qty(5, "foo", "bar") is None
