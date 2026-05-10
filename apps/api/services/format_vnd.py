"""VND currency formatter (cycle AA1, Python half).

Server-side mirror of `apps/web/lib/format-vnd.ts`. Used by:

  * The audit CSV / pinned-export columns where amount columns
    appear (estimate.approve, change_order.approve, etc).
  * The Slack alert digest body (`spec.body` strings include
    formatted amounts inline).
  * The email digest renderer.

  format_vnd(amount)   — `12.345.678 ₫`
  parse_vnd(input)     — `"12.345.678 ₫"` → 12345678

Pure stdlib — no babel, no babel.numbers, no Vietnamese-specific
locale data. The conventions are stable enough to inline.

Rounding: half-toward-positive-infinity to match JS `Math.round`
(NOT Python's banker's rounding). A refactor that uses `round()`
would silently shift halves between languages — pin via tests.
"""

from __future__ import annotations

import math
import re

# Vietnamese đồng sign U+20AB. NOT 'đ' (lowercase d-stroke, used
# informally in Vietnamese typing) and NOT 'VND' (text abbreviation).
VND_SYMBOL = "₫"


# Vietnamese convention is `.` for thousands. A refactor that swaps
# to ',' would diverge from every Vietnamese government-issued
# financial document and the JS half.
VND_THOUSANDS_SEPARATOR = "."


# Vietnamese convention is `,` for decimal (`1,5` means 1.5). VND
# has no decimal in modern pricing — exposed for callers that format
# other currencies via the same conventions.
VND_DECIMAL_SEPARATOR = ","


_PARSE_STRIP = re.compile(r"đ|VND", re.IGNORECASE)


def _js_round(x: float) -> int:
    """Match JS `Math.round`: round half toward +infinity.

    Python's built-in `round()` uses banker's rounding (half to
    even), which would format `1234.5` as `1.234 ₫` instead of
    `1.235 ₫`. Use `math.floor(x + 0.5)` to match the JS half.
    """
    return int(math.floor(x + 0.5))


def format_vnd(amount: int | float | None) -> str:
    """Format a numeric amount as `12.345.678 ₫`.

    None / NaN / inf → "" (no-op for chained renderers — calling
    code can do `format_vnd(row.amount)` without a None check).

    Fractional input rounds to nearest integer (half-up). Negatives
    get a leading `-` (no parentheses accounting format).
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
    sign = "-" if rounded < 0 else ""
    abs_str = str(abs(rounded))
    parts: list[str] = []
    i = len(abs_str)
    while i > 0:
        parts.append(abs_str[max(0, i - 3) : i])
        i -= 3
    parts.reverse()
    return f"{sign}{VND_THOUSANDS_SEPARATOR.join(parts)} {VND_SYMBOL}"


def parse_vnd(input: str | None) -> int | None:
    """Parse a VND-formatted string back to an integer.

    Round-trips `format_vnd` output. Also accepts:
      * Plain integer strings: `"12345678"` → 12345678.
      * Lowercase `đ`: `"12.345.678 đ"` → 12345678 (informal).
      * Text `VND` suffix: `"12345678 VND"` → 12345678.

    Empty / None / non-numeric → None (graceful fallback for
    hand-edited filter URLs).
    """
    if input is None or input == "":
        return None
    cleaned = input.replace(VND_SYMBOL, "")
    cleaned = _PARSE_STRIP.sub("", cleaned)
    cleaned = cleaned.replace(VND_THOUSANDS_SEPARATOR, "")
    cleaned = cleaned.strip()
    if cleaned == "":
        return None
    try:
        n = float(cleaned)
    except ValueError:
        return None
    if math.isnan(n) or math.isinf(n):
        return None
    return int(n)
