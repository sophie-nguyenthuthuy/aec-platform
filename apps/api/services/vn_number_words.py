"""Vietnamese number-to-words for invoice receipts (cycle II3).

VN tax law requires invoice receipts to display the amount in
words ("Số tiền viết bằng chữ"). This module converts integer
VND amounts into the canonical Vietnamese-prose form.

  vnd_to_words(amount)   — "Một triệu hai trăm... đồng"

Edge cases pinned by tests:
  * 0 → "Không đồng".
  * 21 → "Hai mươi MỐT đồng" (NOT "một" — `mốt`/`một` rule).
  * 15 → "Mười LĂM đồng" (NOT "năm" — `lăm`/`năm` rule).
  * 105 → "Một trăm linh năm đồng" (`linh` connector when tens=0).
  * Negative → "Âm <words> đồng".
  * Fractional input rounded via JS-compatible half-up.

Vietnamese number-word rules:

  Units (0-9):
    không, một, hai, ba, bốn, năm, sáu, bảy, tám, chín

  Tens:
    10        → mười
    20-90     → "X mươi"
    11        → mười một    (tens=1: units '1' stays 'một')
    21        → hai mươi MỐT (tens=2-9: units '1' becomes 'mốt')
    15        → mười LĂM    (tens=1: units '5' becomes 'lăm')
    25        → hai mươi LĂM (tens=2-9: units '5' becomes 'lăm')

  Hundreds:
    100       → một trăm
    105       → một trăm LINH năm   (`linh` connector for tens=0)

  Thousands+:
    Suffixes: nghìn (10^3), triệu (10^6), tỷ (10^9).
    Beyond tỷ: composite "X nghìn tỷ" / "X triệu tỷ" / "X tỷ tỷ".

  Non-first trios with hundreds=0:
    Long form: "không trăm" prefix preserved.
    1,005 → "một nghìn không trăm linh năm" (formal invoice form).

Pure stdlib.
"""

from __future__ import annotations

import math

_ONES: tuple[str, ...] = (
    "không",
    "một",
    "hai",
    "ba",
    "bốn",
    "năm",
    "sáu",
    "bảy",
    "tám",
    "chín",
)


def _js_round(x: float) -> int:
    """JS-compatible Math.round: floor(x + 0.5)."""
    return int(math.floor(x + 0.5))


def _trio_to_words(n: int, is_first: bool) -> str:
    """Convert 0-999 into Vietnamese words.

    `is_first` is True only for the most-significant trio of the
    full number (skips the leading "không trăm" filler).

    Returns "" for n=0 (caller should skip empty trios).
    """
    if n == 0:
        return ""

    hundreds = n // 100
    tens = (n // 10) % 10
    units = n % 10

    parts: list[str] = []

    if hundreds > 0:
        parts.append(f"{_ONES[hundreds]} trăm")
    elif not is_first:
        # Non-first trio with hundreds=0 → include "không trăm"
        # connector for invoice-formal clarity.
        parts.append("không trăm")

    if tens > 1:
        parts.append(f"{_ONES[tens]} mươi")
        if units == 1:
            # `mốt` rule: '1' after `X mươi` (tens 2-9) becomes mốt.
            parts.append("mốt")
        elif units == 5:
            # `lăm` rule: '5' after tens word becomes lăm.
            parts.append("lăm")
        elif units > 0:
            parts.append(_ONES[units])
    elif tens == 1:
        parts.append("mười")
        if units == 5:
            parts.append("lăm")
        elif units > 0:
            # NOTE: '1' after `mười` stays `một` (NOT mốt). The
            # `mốt` rule applies only to `X mươi` for X ≥ 2.
            parts.append(_ONES[units])
    else:  # tens == 0
        if units > 0:
            # Add `linh` connector if there are hundreds OR if
            # this is a non-first trio (which has the implicit
            # "không trăm" filler).
            if hundreds > 0 or not is_first:
                parts.append("linh")
            parts.append(_ONES[units])

    return " ".join(parts)


def _scale_label(i: int) -> str:
    """Scale label for trio at position `i` (10^(3i)).

      * i=0 → "" (units)
      * i=1 → "nghìn"
      * i=2 → "triệu"
      * i=3 → "tỷ"
      * i=4 → "nghìn tỷ"   (10^12)
      * i=5 → "triệu tỷ"   (10^15)
      * i=6 → "tỷ tỷ"      (10^18)

    Pattern: every 3 positions adds another "tỷ".
    """
    if i == 0:
        return ""
    base_scales = ("nghìn", "triệu", "tỷ")
    base = base_scales[(i - 1) % 3]
    high_count = (i - 1) // 3
    if high_count == 0:
        return base
    return base + (" tỷ" * high_count)


def _to_words_positive(n: int) -> str:
    """Convert a positive integer to Vietnamese words (without
    the trailing đồng)."""
    if n == 0:
        return "không"

    # Split into trios from least significant.
    trios: list[int] = []
    rem = n
    while rem > 0:
        trios.append(rem % 1000)
        rem //= 1000

    n_trios = len(trios)
    parts: list[str] = []
    for i in range(n_trios - 1, -1, -1):
        trio = trios[i]
        if trio == 0:
            # Skip empty trio — no "không nghìn" filler at trio
            # boundary (only within-trio fillers).
            continue
        is_first = i == n_trios - 1
        words = _trio_to_words(trio, is_first)
        scale = _scale_label(i)
        if scale:
            parts.append(f"{words} {scale}")
        else:
            parts.append(words)

    return " ".join(parts)


def vnd_to_words(amount: int | float | None) -> str:
    """Convert a VND amount to Vietnamese-prose form for invoices.

    Examples:
      * vnd_to_words(0)         → "Không đồng"
      * vnd_to_words(1)         → "Một đồng"
      * vnd_to_words(21)        → "Hai mươi mốt đồng"
      * vnd_to_words(15)        → "Mười lăm đồng"
      * vnd_to_words(105)       → "Một trăm linh năm đồng"
      * vnd_to_words(1234567)   → "Một triệu hai trăm ba mươi bốn nghìn năm trăm sáu mươi bảy đồng"
      * vnd_to_words(-1234)     → "Âm một nghìn hai trăm ba mươi bốn đồng"
      * vnd_to_words(None)      → ""
      * vnd_to_words(NaN/inf)   → ""

    Fractional input rounded via JS-compatible half-up so the
    Python and (future) TS halves agree on rounding boundaries.
    """
    if amount is None:
        return ""
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return ""
    if math.isnan(a) or math.isinf(a):
        return ""

    rounded = _js_round(a)

    if rounded == 0:
        return "Không đồng"

    words = "âm " + _to_words_positive(-rounded) if rounded < 0 else _to_words_positive(rounded)

    # Capitalize first letter (Vietnamese sentence-case).
    words = words[0].upper() + words[1:]
    return f"{words} đồng"
