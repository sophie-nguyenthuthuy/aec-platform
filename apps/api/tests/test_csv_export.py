"""CSV export field escaper (cycle AA2).

Pinned seams:
  1. None → '' (empty cell, NOT the literal 'None').
  2. Embedded quote doubles + wraps (RFC 4180).
  3. Embedded comma / newline / CR force wrap.
  4. Leading =/+/-/@ get single-quote prefix (Excel formula-
     injection defense).
  5. Formula prefix applied BEFORE quote-wrap (attacker can't
     bypass via embedded quotes).
  6. format_iso_for_csv outputs `YYYY-MM-DDTHH:MM:SSZ` with no
     microseconds.
  7. Naive datetimes assumed UTC; aware datetimes converted to UTC.
  8. BOM_UTF8 is U+FEFF.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.csv_export import (
    BOM_UTF8,
    escape_csv_field,
    format_csv_row,
    format_iso_for_csv,
)


# ---------- BOM_UTF8 ----------


def test_bom_utf8_is_zero_width_no_break_space():
    """U+FEFF — without it, Excel-on-Windows renders Vietnamese
    diacritics as mojibake. Pin so a refactor that drops the BOM
    surfaces here."""
    assert BOM_UTF8 == "﻿"
    assert len(BOM_UTF8) == 1


# ---------- escape_csv_field ----------


def test_escape_none_returns_empty_string():
    """Pin: NOT 'None' (the str(None) result). An audit row with
    NULL in an optional column should render as an empty cell."""
    assert escape_csv_field(None) == ""


def test_escape_plain_string_returns_as_is():
    assert escape_csv_field("hello") == "hello"


def test_escape_empty_string_returns_empty():
    assert escape_csv_field("") == ""


def test_escape_quote_doubles_and_wraps():
    """RFC 4180: embedded '"' → '""' inside quoted field."""
    assert escape_csv_field('say "hi"') == '"say ""hi"""'


def test_escape_comma_wraps_in_quotes():
    assert escape_csv_field("a,b") == '"a,b"'


def test_escape_newline_wraps_in_quotes():
    assert escape_csv_field("line1\nline2") == '"line1\nline2"'


def test_escape_carriage_return_wraps():
    assert escape_csv_field("a\rb") == '"a\rb"'


def test_escape_formula_injection_equals():
    """Leading '=' → prefixed with `'`. Defends against
    `=cmd|'/c calc'` rendering as an Excel formula."""
    assert escape_csv_field("=SUM(A1:A10)") == "'=SUM(A1:A10)"


def test_escape_formula_injection_plus():
    assert escape_csv_field("+1234") == "'+1234"


def test_escape_formula_injection_minus():
    """Leading '-' triggers formula-injection defense — pin so a
    refactor that whitelists negative numbers doesn't slip an
    attacker through with `-2+3+cmd|...`. A legitimately negative
    amount renders with the leading quote, but consumers who
    actually need the number can re-parse — security wins."""
    assert escape_csv_field("-1234") == "'-1234"


def test_escape_formula_injection_at_sign():
    """Leading '@' is a formula in older Excel versions
    (`@SUM`)."""
    assert escape_csv_field("@import") == "'@import"


def test_escape_formula_with_embedded_quote():
    """Formula prefix gets applied first, THEN the quote-wrap.
    Pin order so an attacker can't bypass with embedded quotes:
    the prefix is INSIDE the quoted region."""
    out = escape_csv_field('=cmd|"/c calc"!A1')
    # After prefix: `'=cmd|"/c calc"!A1`
    # Has `"` → wrap, double internal quotes.
    assert out == '"\'=cmd|""/c calc""!A1"'


def test_escape_int_and_float():
    """Non-string values get str()-ed."""
    assert escape_csv_field(42) == "42"
    assert escape_csv_field(3.14) == "3.14"


def test_escape_bool_renders_as_python_string():
    """`True` / `False`. Pin since a refactor to render as `1` /
    `0` would change every boolean column in the audit CSV — and
    the existing exports have already shipped with the Python
    string form."""
    assert escape_csv_field(True) == "True"
    assert escape_csv_field(False) == "False"


def test_escape_does_not_prefix_internal_formula_chars():
    """Only the FIRST character triggers the prefix — `a=b`
    isn't a formula (Excel only treats leading `=` as a formula).
    Pin so a refactor that scans the whole string doesn't garble
    legitimate cells."""
    assert escape_csv_field("a=b") == "a=b"
    assert escape_csv_field("a+b") == "a+b"


# ---------- format_csv_row ----------


def test_format_csv_row_simple():
    assert format_csv_row(["a", "b", "c"]) == "a,b,c"


def test_format_csv_row_with_quotes_and_commas():
    assert format_csv_row(['say "hi"', "a,b", "plain"]) == '"say ""hi""","a,b",plain'


def test_format_csv_row_with_none():
    """None values render as empty cells (NOT 'None'). Pin so a
    refactor that str()-es upstream of this helper doesn't
    accidentally render literal 'None' for null audit columns."""
    assert format_csv_row(["a", None, "c"]) == "a,,c"


def test_format_csv_row_empty():
    assert format_csv_row([]) == ""


def test_format_csv_row_single_field():
    assert format_csv_row(["only"]) == "only"


# ---------- format_iso_for_csv ----------


def test_format_iso_naive_assumes_utc():
    """Project convention: naive datetimes are stored as UTC. Pin
    so a refactor that uses local-time conversion surfaces here
    (the audit columns ARE tz-naive UTC by design)."""
    dt = datetime(2026, 5, 9, 12, 30, 45)
    assert format_iso_for_csv(dt) == "2026-05-09T12:30:45Z"


def test_format_iso_aware_converts_to_utc():
    # 19:30 +07:00 == 12:30 UTC.
    dt = datetime(2026, 5, 9, 19, 30, 45, tzinfo=timezone(timedelta(hours=7)))
    assert format_iso_for_csv(dt) == "2026-05-09T12:30:45Z"


def test_format_iso_strips_microseconds():
    """Microseconds are operationally noise in a CSV — pin off
    so the audit row plaintext export and the CSV agree on
    second-precision."""
    dt = datetime(2026, 5, 9, 12, 30, 45, 123456, tzinfo=timezone.utc)
    assert format_iso_for_csv(dt) == "2026-05-09T12:30:45Z"


def test_format_iso_none_returns_empty():
    assert format_iso_for_csv(None) == ""
