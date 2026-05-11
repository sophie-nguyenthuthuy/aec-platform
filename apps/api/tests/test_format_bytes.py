"""File size formatter (cycle DD3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/format-bytes.test.ts`):
  1. BYTE_UNITS = (B, KB, MB, GB, TB) closed, order matters.
  2. SI base 1000 (NOT 1024).
  3. Bytes < 1000 render as "N B" with no decimal.
  4. KB+ render with 2 decimals.
  5. vi locale uses comma; en locale uses dot.
  6. TB is the cap.
  7. None / NaN / Infinity / negative → "".
"""

from __future__ import annotations

from services.format_bytes import BYTE_UNITS, format_bytes

# ---------- Constants ----------


def test_byte_units_canonical_order():
    assert BYTE_UNITS == ("B", "KB", "MB", "GB", "TB")


def test_byte_units_uses_si_symbols_not_iec():
    """Pin: NOT KiB / MiB / etc. SI base 1000 — file managers
    on macOS / Windows / Linux all use SI by default."""
    assert "KiB" not in BYTE_UNITS
    assert "MiB" not in BYTE_UNITS


# ---------- Bytes range (no decimals) ----------


def test_format_zero_bytes():
    assert format_bytes(0) == "0 B"


def test_format_sub_kilobyte_no_decimals():
    assert format_bytes(1) == "1 B"
    assert format_bytes(99) == "99 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(999) == "999 B"


def test_format_floors_fractional_sub_kilobyte():
    """Bytes are atomic — fractional input floors. Pin so a
    refactor that rounds (999.9 → 1000 B → bug) surfaces."""
    assert format_bytes(999.9) == "999 B"


# ---------- Promotion thresholds ----------


def test_promotes_to_kb_at_1000_si_base():
    """Pin SI base: 1000 → KB, NOT 1024."""
    assert format_bytes(1000) == "1,00 KB"
    # 1024 is NOT special — formats as ~1.02 KB.
    assert format_bytes(1024) == "1,02 KB"


def test_format_kb_two_decimals_vi():
    assert format_bytes(1234) == "1,23 KB"
    assert format_bytes(1500) == "1,50 KB"


def test_promotes_to_mb_at_million():
    assert format_bytes(1_000_000) == "1,00 MB"
    assert format_bytes(1_234_567) == "1,23 MB"


def test_promotes_to_gb_at_billion():
    assert format_bytes(1_000_000_000) == "1,00 GB"
    assert format_bytes(1_234_567_890) == "1,23 GB"


def test_promotes_to_tb_at_trillion():
    assert format_bytes(1_000_000_000_000) == "1,00 TB"
    assert format_bytes(1_234_567_890_123) == "1,23 TB"


def test_caps_at_tb_for_pb_scale():
    """8 PB = 8000 TB. Pin: don't promote to PB — surface the
    'this is unusually huge' signal via a 4-digit TB number."""
    assert format_bytes(8e15) == "8000,00 TB"


# ---------- Locale ----------


def test_default_locale_vi_comma_decimal():
    assert format_bytes(1500) == "1,50 KB"


def test_locale_en_dot_decimal():
    assert format_bytes(1500, "en") == "1.50 KB"
    assert format_bytes(1_234_567_890, "en") == "1.23 GB"


def test_locale_only_affects_decimal_separator():
    """Units are SI symbols regardless of locale."""
    assert format_bytes(1500, "vi").endswith("KB")
    assert format_bytes(1500, "en").endswith("KB")


# ---------- Defensive ----------


def test_format_none_returns_empty():
    assert format_bytes(None) == ""


def test_format_nan_inf_returns_empty():
    assert format_bytes(float("nan")) == ""
    assert format_bytes(float("inf")) == ""
    assert format_bytes(float("-inf")) == ""


def test_format_negative_returns_empty():
    """Negative bytes is a calculation bug upstream — pin ''
    so the row renders empty rather than '-512 B'."""
    assert format_bytes(-1) == ""
    assert format_bytes(-1000) == ""


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """The Python and TS halves must produce the same output for
    every input. Pin via a representative table."""
    cases = [
        (0, "vi", "0 B"),
        (512, "vi", "512 B"),
        (1000, "vi", "1,00 KB"),
        (1234, "vi", "1,23 KB"),
        (1234, "en", "1.23 KB"),
        (1_234_567, "vi", "1,23 MB"),
        (1_234_567_890, "vi", "1,23 GB"),
        (1_234_567_890_123, "vi", "1,23 TB"),
        (8e15, "vi", "8000,00 TB"),
    ]
    for n, locale, expected in cases:
        assert format_bytes(n, locale) == expected, (
            f"format_bytes({n}, {locale!r}) = {format_bytes(n, locale)!r}, expected {expected!r}"
        )
