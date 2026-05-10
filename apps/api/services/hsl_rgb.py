"""HSL/RGB color converter (cycle SS3, Python half).

Server-side mirror of `apps/web/lib/hsl-rgb.ts`. Used by the
chart palette generator, the audit row tone allocator, and any
server-rendered color computation.

  hsl_to_rgb_hex(h, s, lightness)  — "#abcdef" or ""
  rgb_hex_to_hsl(hex)      — HSL or None
  HSL                      — frozen dataclass

Pure stdlib. JS-compatible rounding (matches AA1 / NN3 pattern).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HSL:
    """Hue/Saturation/Lightness color. h ∈ [0, 360); s, lightness ∈ [0, 1]."""

    h: float
    s: float
    l: float  # noqa: E741  # l = lightness; HSL convention


_HEX_RE = re.compile(r"^[0-9a-f]{6}$")


def _js_round(x: float) -> int:
    """JS Math.round-compatible (matches AA1 / NN3 / SS3 TS half)."""
    return int(math.floor(x + 0.5))


def _hue_to_rgb(p: float, q: float, t: float) -> float:
    if t < 0:
        t += 1
    if t > 1:
        t -= 1
    if t < 1 / 6:
        return p + (q - p) * 6 * t
    if t < 1 / 2:
        return q
    if t < 2 / 3:
        return p + (q - p) * (2 / 3 - t) * 6
    return p


def hsl_to_rgb_hex(h: float, s: float, l: float) -> str:  # noqa: E741
    """Convert HSL to RGB hex string `#rrggbb`.

    Returns "" for invalid input (NaN, S/L out of [0, 1]).
    """
    try:
        if not all(math.isfinite(x) for x in (h, s, l)):
            return ""
    except TypeError:
        return ""
    if not (0 <= s <= 1) or not (0 <= l <= 1):
        return ""

    # Normalize hue to [0, 360).
    hue = h % 360
    if hue < 0:
        hue += 360

    if s == 0:
        r = g = b = l
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        h_norm = hue / 360
        r = _hue_to_rgb(p, q, h_norm + 1 / 3)
        g = _hue_to_rgb(p, q, h_norm)
        b = _hue_to_rgb(p, q, h_norm - 1 / 3)

    ri = _js_round(r * 255)
    gi = _js_round(g * 255)
    bi = _js_round(b * 255)

    return f"#{ri:02x}{gi:02x}{bi:02x}"


def rgb_hex_to_hsl(hex_str: str | None) -> HSL | None:
    """Convert RGB hex string to HSL.

    Accepts 3-char shorthand and optional `#` prefix.
    Returns None for invalid input.
    """
    if not hex_str:
        return None
    s = hex_str.strip()
    if not s:
        return None
    if s.startswith("#"):
        s = s[1:]
    s = s.lower()
    if len(s) == 3:
        s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2]
    if not _HEX_RE.match(s):
        return None

    r = int(s[0:2], 16) / 255
    g = int(s[2:4], 16) / 255
    b = int(s[4:6], 16) / 255

    max_v = max(r, g, b)
    min_v = min(r, g, b)
    lightness = (max_v + min_v) / 2

    if max_v == min_v:
        return HSL(h=0.0, s=0.0, l=lightness)

    d = max_v - min_v
    saturation = d / (2 - max_v - min_v) if lightness > 0.5 else d / (max_v + min_v)

    if max_v == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif max_v == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    h /= 6

    return HSL(h=h * 360, s=saturation, l=lightness)
