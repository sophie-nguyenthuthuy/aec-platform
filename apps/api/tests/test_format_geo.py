"""Geographic coordinate parser/formatter (cycle TT1, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-geo.test.ts`):
  1. Lat/lng range validated.
  2. Decimal + DMS parsing.
  3. DMS hemisphere sign flip.
  4. VN bounding box for `is_in_vietnam`.
  5. Cross-language byte-for-byte parity.
"""

from __future__ import annotations

from services.format_geo import (
    DEFAULT_DECIMALS,
    LAT_MAX,
    LAT_MIN,
    LNG_MAX,
    LNG_MIN,
    VN_LAT_BAND,
    VN_LNG_BAND,
    format_lat_lng,
    is_in_vietnam,
    parse_lat_lng,
)

# ---------- Constants ----------


def test_lat_lng_bounds():
    assert LAT_MIN == -90
    assert LAT_MAX == 90
    assert LNG_MIN == -180
    assert LNG_MAX == 180


def test_default_decimals():
    assert DEFAULT_DECIMALS == 6


def test_vn_bands():
    assert VN_LAT_BAND == (8.0, 24.0)
    assert VN_LNG_BAND == (102.0, 110.0)


# ---------- Decimal degree parsing ----------


def test_parse_comma_space():
    assert parse_lat_lng("21.0285, 105.8542") == (21.0285, 105.8542)


def test_parse_comma_only():
    assert parse_lat_lng("21.0285,105.8542") == (21.0285, 105.8542)


def test_parse_space_only():
    assert parse_lat_lng("21.0285 105.8542") == (21.0285, 105.8542)


def test_parse_negative():
    assert parse_lat_lng("-21.0285, -105.8542") == (-21.0285, -105.8542)


def test_parse_explicit_positive():
    assert parse_lat_lng("+21.0, +105.0") == (21.0, 105.0)


def test_parse_integer():
    assert parse_lat_lng("0, 0") == (0, 0)


def test_parse_boundary_lat():
    assert parse_lat_lng("90, 0") == (90, 0)
    assert parse_lat_lng("-90, 0") == (-90, 0)


def test_parse_boundary_lng():
    assert parse_lat_lng("0, 180") == (0, 180)
    assert parse_lat_lng("0, -180") == (0, -180)


# ---------- DMS parsing ----------


def test_parse_dms_canonical():
    result = parse_lat_lng("21°01'42.6\"N 105°51'15.1\"E")
    assert result is not None
    lat, lng = result
    assert abs(lat - 21.0285) < 0.001
    assert abs(lng - 105.8542) < 0.001


def test_parse_dms_south_flips_lat():
    result = parse_lat_lng("21°01'42.6\"S 105°51'15.1\"E")
    lat, _ = result  # type: ignore
    assert abs(lat - (-21.0285)) < 0.001


def test_parse_dms_west_flips_lng():
    result = parse_lat_lng("21°01'42.6\"N 105°51'15.1\"W")
    _, lng = result  # type: ignore
    assert abs(lng - (-105.8542)) < 0.001


def test_parse_dms_lng_first_still_works():
    """Hemisphere letter determines lat vs lng, NOT position."""
    result = parse_lat_lng("105°51'15.1\"E 21°01'42.6\"N")
    assert result is not None
    lat, lng = result
    assert abs(lat - 21.0285) < 0.001
    assert abs(lng - 105.8542) < 0.001


# ---------- Invalid ----------


def test_parse_lat_out_of_range_returns_none():
    assert parse_lat_lng("91, 0") is None
    assert parse_lat_lng("-91, 0") is None


def test_parse_lng_out_of_range_returns_none():
    assert parse_lat_lng("0, 181") is None
    assert parse_lat_lng("0, -181") is None


def test_parse_non_numeric_returns_none():
    assert parse_lat_lng("not-coords") is None
    assert parse_lat_lng("21.0285") is None  # single value


def test_parse_none_and_empty():
    assert parse_lat_lng(None) is None
    assert parse_lat_lng("") is None
    assert parse_lat_lng("   ") is None


# ---------- format_lat_lng ----------


def test_format_default_6_decimals():
    assert format_lat_lng(21.0285, 105.8542) == "21.028500, 105.854200"


def test_format_custom_decimals():
    assert format_lat_lng(21.0285, 105.8542, 4) == "21.0285, 105.8542"


def test_format_zero_decimals():
    assert format_lat_lng(21.5, 105.5, 0) == "22, 106"


def test_format_integer_coords():
    assert format_lat_lng(0, 0) == "0.000000, 0.000000"


def test_format_negative():
    assert format_lat_lng(-21.0285, -105.8542, 4) == "-21.0285, -105.8542"


def test_format_out_of_range_returns_empty():
    assert format_lat_lng(91, 0) == ""
    assert format_lat_lng(0, 181) == ""


def test_format_nan_returns_empty():
    assert format_lat_lng(float("nan"), 0) == ""
    assert format_lat_lng(0, float("nan")) == ""


def test_format_negative_decimals_returns_empty():
    assert format_lat_lng(0, 0, -1) == ""


# ---------- is_in_vietnam ----------


def test_in_vietnam_hanoi():
    assert is_in_vietnam(21.0285, 105.8542) is True


def test_in_vietnam_hcm():
    assert is_in_vietnam(10.7626, 106.6602) is True


def test_in_vietnam_da_nang():
    assert is_in_vietnam(16.0544, 108.2022) is True


def test_not_in_vietnam_nyc():
    assert is_in_vietnam(40.7128, -74.0060) is False


def test_not_in_vietnam_tokyo():
    assert is_in_vietnam(35.6762, 139.6503) is False


def test_swapped_lat_lng_caught():
    """Cardinal pin: typo that flips lat/lng. Hanoi values
    swapped → 105.8542 as lat (out of [-90, 90]) → False."""
    assert is_in_vietnam(105.8542, 21.0285) is False


def test_invalid_input():
    assert is_in_vietnam(float("nan"), 100) is False
    assert is_in_vietnam(91, 100) is False


# ---------- Round-trip ----------


def test_round_trip():
    parsed = parse_lat_lng("21.028500, 105.854200")
    assert parsed is not None
    formatted = format_lat_lng(parsed[0], parsed[1])
    assert formatted == "21.028500, 105.854200"


# ---------- Cross-language consistency ----------


def test_matches_ts_half_decimal_cases():
    """Cross-language pin: canonical decimal cases."""
    cases = [
        ("21.0285, 105.8542", (21.0285, 105.8542)),
        ("-21.0285, -105.8542", (-21.0285, -105.8542)),
        ("0, 0", (0.0, 0.0)),
        ("90, 0", (90.0, 0.0)),
        ("not-coords", None),
        (None, None),
    ]
    for input_str, expected in cases:
        result = parse_lat_lng(input_str)
        assert result == expected, f"parse_lat_lng({input_str!r}) = {result!r}, expected {expected!r}"


def test_matches_ts_format_canonical():
    """Pin: format output identical for canonical inputs."""
    assert format_lat_lng(21.0285, 105.8542) == "21.028500, 105.854200"
    assert format_lat_lng(0, 0) == "0.000000, 0.000000"
    assert format_lat_lng(-21.0285, -105.8542, 4) == "-21.0285, -105.8542"
