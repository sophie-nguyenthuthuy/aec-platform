"""File size formatter (cycle DD3, Python half).

Server-side mirror of `apps/web/lib/format-bytes.ts`. Used by:

  * The webhook delivery CSV / pinned-export columns where
    payload sizes appear.
  * The Slack alert digest's "uploaded a 12,3 MB attachment"
    body strings.
  * The audit row plaintext export.

  format_bytes(n, locale)   — render bytes in B / KB / MB / GB / TB
  BYTE_UNITS                — closed unit table

Convention:
  * SI base 1000 (NOT 1024).
  * `locale='vi'` (default) uses comma decimal: "1,23 KB".
  * `locale='en'` uses dot decimal: "1.23 KB".
  * Bytes < 1000 render as "512 B" (no decimal, atomic).
  * TB is the cap (8 PB → "8000,00 TB" not "8 PB").

Pure stdlib.
"""

from __future__ import annotations

import math
from typing import Literal

# Closed unit table. Order matters — promotion walks left-to-right
# at the SI 1000 boundary. Pin so a refactor that inserts e.g.
# 'KiB' surfaces here.
BYTE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB")


ByteLocale = Literal["vi", "en"]


def _js_round_2dp(x: float) -> float:
    """Round to 2 decimals using JS-compatible half-up semantics
    (NOT Python's banker's rounding). Matches the TS half's
    `Math.round(value * 100) / 100`."""
    return math.floor(x * 100 + 0.5) / 100


def format_bytes(
    n: int | float | None,
    locale: ByteLocale = "vi",
) -> str:
    """Format a byte count as a localized human-readable string.

    * format_bytes(0)         → "0 B"
    * format_bytes(512)       → "512 B"
    * format_bytes(1500)      → "1,50 KB"
    * format_bytes(1500, "en") → "1.50 KB"
    * format_bytes(8e15)      → "8000,00 TB" (PB capped at TB)
    * format_bytes(None)      → ""
    * format_bytes(float('nan')) → ""
    * format_bytes(-1)        → ""           (negative is a bug)
    """
    if n is None:
        return ""
    try:
        a = float(n)
    except (TypeError, ValueError):
        return ""
    if math.isnan(a) or math.isinf(a):
        return ""
    if a < 0:
        return ""
    if a < 1000:
        # Bytes are atomic — floor fractional input rather than
        # round (you can't have 999.9 bytes).
        return f"{int(a)} B"

    value = a
    unit_idx = 0
    while value >= 1000 and unit_idx < len(BYTE_UNITS) - 1:
        value /= 1000
        unit_idx += 1

    rounded = _js_round_2dp(value)
    decimal = "," if locale == "vi" else "."
    text = f"{rounded:.2f}".replace(".", decimal)
    return f"{text} {BYTE_UNITS[unit_idx]}"
