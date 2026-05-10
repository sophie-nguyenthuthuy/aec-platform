"""VND currency formatter (cycle AA1, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-vnd.test.ts`):
  1. VND_SYMBOL is U+20AB (đồng sign), not 'đ' or 'VND'.
  2. VND_THOUSANDS_SEPARATOR is '.' (Vietnamese convention).
  3. format_vnd(12345678) == '12.345.678 ₫'.
  4. parse_vnd round-trips format_vnd output.
  5. None / NaN / Infinity → '' (no-op for chained renderers).
  6. parse_vnd graceful None on non-numeric input.
  7. JS-compatible rounding: 1234.5 → '1.235 ₫' (half up, not banker's).
"""

from __future__ import annotations

from services.format_vnd import (
    VND_SYMBOL,
    VND_THOUSANDS_SEPARATOR,
    format_vnd,
    parse_vnd,
)

# ---------- Constants ----------


def test_vnd_symbol_is_dong_sign():
    assert VND_SYMBOL == "₫"
    # Pin: NOT 'đ' (lowercase d-stroke) and NOT 'VND' (text abbrev).
    assert VND_SYMBOL != "đ"
    assert VND_SYMBOL != "VND"


def test_vnd_thousands_separator_is_dot():
    assert VND_THOUSANDS_SEPARATOR == "."


# ---------- format_vnd ----------


def test_format_vnd_canonical():
    assert format_vnd(12345678) == "12.345.678 ₫"


def test_format_vnd_small_amounts():
    assert format_vnd(0) == "0 ₫"
    assert format_vnd(99) == "99 ₫"
    assert format_vnd(999) == "999 ₫"
    assert format_vnd(1000) == "1.000 ₫"


def test_format_vnd_large_amounts():
    assert format_vnd(1_000_000_000) == "1.000.000.000 ₫"


def test_format_vnd_rounds_half_up_not_bankers():
    """JS Math.round rounds half toward +infinity (1234.5 → 1235).
    Python's built-in round() uses banker's rounding (half to
    even, 1234.5 → 1234). Pin the half-up behavior so the Python
    and TS halves format the same fractional input identically."""
    assert format_vnd(1234.5) == "1.235 ₫"
    assert format_vnd(1234.4) == "1.234 ₫"


def test_format_vnd_negative():
    assert format_vnd(-12345) == "-12.345 ₫"


def test_format_vnd_none_returns_empty():
    assert format_vnd(None) == ""


def test_format_vnd_nan_inf_return_empty():
    assert format_vnd(float("nan")) == ""
    assert format_vnd(float("inf")) == ""
    assert format_vnd(float("-inf")) == ""


# ---------- parse_vnd ----------


def test_parse_vnd_round_trips():
    assert parse_vnd("12.345.678 ₫") == 12345678


def test_parse_vnd_accepts_plain_integer_strings():
    assert parse_vnd("12345678") == 12345678
    assert parse_vnd("0") == 0


def test_parse_vnd_accepts_amount_without_symbol():
    assert parse_vnd("12.345.678") == 12345678


def test_parse_vnd_accepts_lowercase_dong():
    """Hand-typed `đ` is the most common informal symbol — accept
    so a saved URL like `?max_amount=12.345.678 đ` works."""
    assert parse_vnd("12.345.678 đ") == 12345678


def test_parse_vnd_accepts_vnd_text_suffix():
    assert parse_vnd("12345678 VND") == 12345678
    assert parse_vnd("12345678 vnd") == 12345678


def test_parse_vnd_negative():
    assert parse_vnd("-12.345 ₫") == -12345


def test_parse_vnd_none_and_empty_return_none():
    assert parse_vnd(None) is None
    assert parse_vnd("") is None


def test_parse_vnd_non_numeric_returns_none():
    """Stale URLs with `?max_amount=một triệu` shouldn't crash —
    graceful None fallback."""
    assert parse_vnd("abc") is None
    assert parse_vnd("một triệu") is None


def test_parse_vnd_strips_to_empty_returns_none():
    """An input of just '.' or '₫' coerces to empty after
    stripping — pin None rather than 0 (the empty-string parse
    is a stale-URL signal, not a legitimate zero amount)."""
    assert parse_vnd("...") is None
    assert parse_vnd("₫") is None


# ---------- Cross-language consistency ----------


def test_round_trip_through_both_helpers():
    """A round-trip through format → parse must preserve exact
    integer value. Pin so a refactor that introduces a divergence
    (e.g. format adds a no-break space the parser doesn't strip)
    surfaces here."""
    for amount in [0, 1, 999, 1_000, 12_345, 1_000_000_000, -12_345]:
        formatted = format_vnd(amount)
        parsed = parse_vnd(formatted)
        assert parsed == amount, f"round-trip lost: {amount} → {formatted!r} → {parsed!r}"
