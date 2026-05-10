"""Estimate quantity unit normalizer (cycle MM2).

Closed registry of VN AEC procurement units. Today the estimate
line-item validator, the quantity-display formatter, and the
audit row's quantity-impact detector each handle units inline
with subtly different aliasing. This module is the single source
of truth.

  parse_unit(input)              — canonical unit or None
  unit_dimension(unit)           — "weight"/"length"/"area"/"volume"/"count"/None
  convert_qty(qty, from, to)     — converted qty or None
  UNITS                          — closed unit set
  UnitDimension                  — Literal type

Composes with BB3 (`strip_vn_diacritics`) for ASCII-aliased
input normalization (e.g. "tan" → "tấn").

Pinned invariants:
  * 1 tấn = 1000 kg (Vietnamese metric — NOT 1 ton US = 907 kg).
  * 1 tạ = 100 kg.
  * Different dimensions don't auto-convert (m³ ↔ m² → None).
  * Count units (hộp, bộ, cái, chiếc, viên, tấm) have NO conversion
    between distinct units (each is operationally its own thing).
  * Same-unit identity always succeeds (`convert_qty(5, "kg", "kg")` = 5).

Pure stdlib + BB3.
"""

from __future__ import annotations

from typing import Literal

from services.strip_vn_diacritics import strip_vn_diacritics

UnitDimension = Literal["weight", "length", "area", "volume", "count"]


# Canonical unit → dimension. Keyed by the Vietnamese-native
# canonical form (with diacritics where applicable).
_UNIT_DIMENSIONS: dict[str, UnitDimension] = {
    # Weight
    "g": "weight",
    "kg": "weight",
    "tấn": "weight",
    "tạ": "weight",
    "lạng": "weight",
    # Length
    "mm": "length",
    "cm": "length",
    "m": "length",
    "km": "length",
    # Area
    "cm²": "area",
    "m²": "area",
    # Volume
    "lít": "volume",
    "m³": "volume",
    # Count (each is operationally its own — no inter-conversion)
    "hộp": "count",
    "bộ": "count",
    "cái": "count",
    "chiếc": "count",
    "viên": "count",
    "tấm": "count",
}


# Closed set of valid units (computed for export).
UNITS: frozenset[str] = frozenset(_UNIT_DIMENSIONS.keys())


# Conversion factors to base unit within each dimension.
# Base: kg (weight), m (length), m² (area), m³ (volume).
# Count units have no factor (no inter-conversion allowed).
_TO_BASE: dict[str, float] = {
    # Weight (base: kg)
    "g": 0.001,
    "kg": 1.0,
    "tấn": 1000.0,  # 1 tấn = 1000 kg (VN metric)
    "tạ": 100.0,  # 1 tạ = 100 kg
    "lạng": 0.1,  # 1 lạng = 100g = 0.1 kg
    # Length (base: m)
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "km": 1000.0,
    # Area (base: m²)
    "cm²": 0.0001,
    "m²": 1.0,
    # Volume (base: m³ for solids; lít stored as 0.001 m³ for
    # cross-dimension consistency, though the area / liquid
    # distinction is operationally separate)
    "lít": 0.001,
    "m³": 1.0,
}


# Aliases: ASCII-normalized form → canonical Vietnamese form.
# Used for round-trip parsing of user input typed without
# diacritics (common when input comes from a barcode scanner
# or a CSV import).
_ALIASES: dict[str, str] = {
    "tan": "tấn",
    "ta": "tạ",
    "lang": "lạng",
    "lit": "lít",
    "m2": "m²",
    "m3": "m³",
    "cm2": "cm²",
    "hop": "hộp",
    "bo": "bộ",
    "cai": "cái",
    "chiec": "chiếc",
    "vien": "viên",
    "tam": "tấm",
}


def parse_unit(input_str: str | None) -> str | None:
    """Normalize a unit string to its canonical Vietnamese form.

    Strategy:
      1. Lowercase + boundary-strip.
      2. Try direct lookup in canonical units.
      3. Try ASCII-alias lookup.
      4. Try diacritic-stripped + lowercase + alias lookup
         (composes with BB3 `strip_vn_diacritics`).

    Returns None for unknown units.
    """
    if not input_str:
        return None
    s = input_str.strip().lower()
    if not s:
        return None

    # Direct lookup
    if s in _UNIT_DIMENSIONS:
        return s

    # Alias lookup
    if s in _ALIASES:
        return _ALIASES[s]

    # Diacritic-strip + alias lookup
    stripped = strip_vn_diacritics(s).lower()
    if stripped in _ALIASES:
        return _ALIASES[stripped]

    return None


def unit_dimension(unit: str | None) -> UnitDimension | None:
    """Return the dimension of a unit ("weight", "length",
    "area", "volume", "count") or None for unknown."""
    canonical = parse_unit(unit)
    if canonical is None:
        return None
    return _UNIT_DIMENSIONS.get(canonical)


def convert_qty(
    qty: float,
    from_unit: str,
    to_unit: str,
) -> float | None:
    """Convert `qty` from `from_unit` to `to_unit`.

    Returns the converted quantity, or None when:
      * Either unit is unknown.
      * Units are different dimensions (e.g. kg ↔ m).
      * Both units are count dimension but different units
        (e.g. hộp → bộ).

    Same-unit identity always succeeds: `convert_qty(5, "kg", "kg")` = 5.
    """
    from_canonical = parse_unit(from_unit)
    to_canonical = parse_unit(to_unit)
    if from_canonical is None or to_canonical is None:
        return None

    # Same-unit identity.
    if from_canonical == to_canonical:
        return float(qty)

    from_dim = _UNIT_DIMENSIONS[from_canonical]
    to_dim = _UNIT_DIMENSIONS[to_canonical]
    if from_dim != to_dim:
        return None

    # Count units don't inter-convert.
    if from_dim == "count":
        return None

    from_factor = _TO_BASE[from_canonical]
    to_factor = _TO_BASE[to_canonical]
    return qty * from_factor / to_factor
