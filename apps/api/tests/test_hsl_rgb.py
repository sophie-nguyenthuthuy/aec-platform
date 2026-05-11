"""HSL/RGB color converter (cycle SS3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/hsl-rgb.test.ts`):
  1. Pure colors (red/green/blue) exact hex.
  2. Achromatic (black/white/gray) → s=0.
  3. Hue wraps via modulo.
  4. S/L out of [0, 1] → "" / None (not clamped).
  5. 3-char shorthand expanded.
  6. Round-trip stable within ±1 unit.
  7. Cross-language byte-for-byte parity.
"""

from __future__ import annotations

from services.hsl_rgb import HSL, hsl_to_rgb_hex, rgb_hex_to_hsl

# ---------- hsl_to_rgb_hex — pure colors ----------


def test_pure_red():
    assert hsl_to_rgb_hex(0, 1, 0.5) == "#ff0000"


def test_pure_green():
    assert hsl_to_rgb_hex(120, 1, 0.5) == "#00ff00"


def test_pure_blue():
    assert hsl_to_rgb_hex(240, 1, 0.5) == "#0000ff"


def test_yellow():
    assert hsl_to_rgb_hex(60, 1, 0.5) == "#ffff00"


def test_cyan():
    assert hsl_to_rgb_hex(180, 1, 0.5) == "#00ffff"


def test_magenta():
    assert hsl_to_rgb_hex(300, 1, 0.5) == "#ff00ff"


# ---------- Achromatic ----------


def test_black():
    assert hsl_to_rgb_hex(0, 0, 0) == "#000000"


def test_white():
    assert hsl_to_rgb_hex(0, 0, 1) == "#ffffff"


def test_mid_gray():
    assert hsl_to_rgb_hex(0, 0, 0.5) == "#808080"


# ---------- Hue wrap ----------


def test_hue_360_wraps_to_0():
    assert hsl_to_rgb_hex(360, 1, 0.5) == "#ff0000"


def test_hue_720_wraps():
    assert hsl_to_rgb_hex(720, 1, 0.5) == "#ff0000"


def test_negative_hue_wraps():
    """-120 = 240 (blue)."""
    assert hsl_to_rgb_hex(-120, 1, 0.5) == "#0000ff"


# ---------- Invalid input ----------


def test_nan_hue_returns_empty():
    assert hsl_to_rgb_hex(float("nan"), 0.5, 0.5) == ""


def test_inf_hue_returns_empty():
    assert hsl_to_rgb_hex(float("inf"), 0.5, 0.5) == ""


def test_s_out_of_range_returns_empty():
    """Cardinal pin: NOT clamped — surfaces config bug."""
    assert hsl_to_rgb_hex(0, -0.1, 0.5) == ""
    assert hsl_to_rgb_hex(0, 1.1, 0.5) == ""


def test_l_out_of_range_returns_empty():
    assert hsl_to_rgb_hex(0, 0.5, -0.1) == ""
    assert hsl_to_rgb_hex(0, 0.5, 1.1) == ""


def test_s_boundary_zero():
    assert hsl_to_rgb_hex(0, 0, 0.5) == "#808080"


def test_s_boundary_one():
    assert hsl_to_rgb_hex(0, 1, 0.5) == "#ff0000"


# ---------- rgb_hex_to_hsl ----------


def test_rgb_hex_to_hsl_red():
    result = rgb_hex_to_hsl("#ff0000")
    assert result is not None
    assert abs(result.h - 0.0) < 1e-5
    assert abs(result.s - 1.0) < 1e-5
    assert abs(result.l - 0.5) < 1e-5


def test_rgb_hex_to_hsl_green():
    result = rgb_hex_to_hsl("#00ff00")
    assert result is not None
    assert abs(result.h - 120.0) < 1e-5


def test_rgb_hex_to_hsl_blue():
    result = rgb_hex_to_hsl("#0000ff")
    assert result is not None
    assert abs(result.h - 240.0) < 1e-5


def test_rgb_hex_to_hsl_black():
    assert rgb_hex_to_hsl("#000000") == HSL(h=0.0, s=0.0, l=0.0)


def test_rgb_hex_to_hsl_white():
    assert rgb_hex_to_hsl("#ffffff") == HSL(h=0.0, s=0.0, l=1.0)


def test_rgb_hex_to_hsl_gray():
    """Gray has zero saturation."""
    result = rgb_hex_to_hsl("#808080")
    assert result is not None
    assert result.s == 0.0


# ---------- Input format ----------


def test_3_char_shorthand():
    short = rgb_hex_to_hsl("#f00")
    long = rgb_hex_to_hsl("#ff0000")
    assert short == long


def test_no_hash_prefix():
    assert rgb_hex_to_hsl("ff0000") == rgb_hex_to_hsl("#ff0000")


def test_case_insensitive():
    assert rgb_hex_to_hsl("#FF0000") == rgb_hex_to_hsl("#ff0000")


def test_whitespace_stripped():
    assert rgb_hex_to_hsl("  #ff0000  ") == rgb_hex_to_hsl("#ff0000")


# ---------- Invalid hex ----------


def test_none_returns_none():
    assert rgb_hex_to_hsl(None) is None


def test_empty_returns_none():
    assert rgb_hex_to_hsl("") is None


def test_non_hex_returns_none():
    assert rgb_hex_to_hsl("not-a-hex") is None


def test_wrong_length():
    assert rgb_hex_to_hsl("#fff0") is None  # 4 chars
    assert rgb_hex_to_hsl("#fffff") is None  # 5 chars


# ---------- Round-trip ----------


def test_round_trip_pure_red():
    hsl = rgb_hex_to_hsl("#ff0000")
    assert hsl is not None
    assert hsl_to_rgb_hex(hsl.h, hsl.s, hsl.l) == "#ff0000"


def test_round_trip_pure_blue():
    hsl = rgb_hex_to_hsl("#0000ff")
    assert hsl is not None
    assert hsl_to_rgb_hex(hsl.h, hsl.s, hsl.l) == "#0000ff"


def test_round_trip_black():
    hsl = rgb_hex_to_hsl("#000000")
    assert hsl is not None
    assert hsl_to_rgb_hex(hsl.h, hsl.s, hsl.l) == "#000000"


def test_round_trip_arbitrary_within_one_unit():
    """Float quantization may drift by 1 RGB unit — pin tolerance."""
    inputs = ["#3a5c8e", "#fc7d12", "#4caf50"]
    for hex_in in inputs:
        hsl = rgb_hex_to_hsl(hex_in)
        assert hsl is not None
        round_back = rgb_hex_to_hsl(hsl_to_rgb_hex(hsl.h, hsl.s, hsl.l))
        assert round_back is not None
        assert abs(round_back.h - hsl.h) <= 1.0
        assert abs(round_back.s - hsl.s) <= 0.01
        assert abs(round_back.l - hsl.l) <= 0.01


# ---------- Frozen ----------


def test_hsl_is_frozen():
    h = HSL(h=0.0, s=1.0, l=0.5)
    try:
        h.h = 120.0  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("HSL should be frozen")


# ---------- Cross-language consistency ----------


def test_matches_ts_half_pure_colors():
    """Cross-language pin: pure-color hex outputs identical
    in both halves."""
    cases = [
        (0, 1, 0.5, "#ff0000"),
        (120, 1, 0.5, "#00ff00"),
        (240, 1, 0.5, "#0000ff"),
        (60, 1, 0.5, "#ffff00"),
        (180, 1, 0.5, "#00ffff"),
        (300, 1, 0.5, "#ff00ff"),
        (0, 0, 0, "#000000"),
        (0, 0, 1, "#ffffff"),
        (0, 0, 0.5, "#808080"),
    ]
    for h, s, l, expected in cases:  # noqa: E741
        assert hsl_to_rgb_hex(h, s, l) == expected, (
            f"hsl_to_rgb_hex({h}, {s}, {l}) = {hsl_to_rgb_hex(h, s, l)!r}, expected {expected!r}"
        )
