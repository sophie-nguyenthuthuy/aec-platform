"""Geographic coordinate parser/formatter (cycle TT1, Python half).

Server-side mirror of `apps/web/lib/format-geo.ts`. Used by the
project location validator, the audit row's coordinate column,
and the RFQ delivery-address geo lookup.

  parse_lat_lng(input)              — (lat, lng) tuple or None
  format_lat_lng(lat, lng, decimals) — "21.028500, 105.854200" or ""
  is_in_vietnam(lat, lng)            — bool

Pure stdlib.
"""

from __future__ import annotations

import math
import re

LAT_MIN = -90
LAT_MAX = 90
LNG_MIN = -180
LNG_MAX = 180
DEFAULT_DECIMALS = 6


VN_LAT_BAND: tuple[float, float] = (8.0, 24.0)
VN_LNG_BAND: tuple[float, float] = (102.0, 110.0)


_DECIMAL_PAIR_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)\s*$")


_DMS_PIECE_RE = re.compile(
    r'(\d+)\s*°\s*(\d+)\s*\'\s*(\d+(?:\.\d+)?)\s*"?\s*([NSEW])',
    re.IGNORECASE,
)


def _validate(lat: float, lng: float) -> bool:
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    return LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX


def _dms_to_decimal(deg: int, minute: int, sec: float, hemi: str) -> float:
    decimal = deg + minute / 60 + sec / 3600
    if hemi.upper() in ("S", "W"):
        return -decimal
    return decimal


def parse_lat_lng(input_str: str | None) -> tuple[float, float] | None:
    """Parse a coordinate pair string.

    Accepts decimal degrees and DMS notation. Returns
    `(lat, lng)` tuple or None.
    """
    if not input_str:
        return None
    s = input_str.strip()
    if not s:
        return None

    # Try decimal pair.
    m = _DECIMAL_PAIR_RE.match(s)
    if m:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
        except ValueError:
            return None
        if _validate(lat, lng):
            return (lat, lng)
        return None

    # Try DMS pair.
    pieces = list(_DMS_PIECE_RE.finditer(s))
    if len(pieces) == 2:
        lat: float | None = None
        lng: float | None = None
        for p in pieces:
            deg = int(p.group(1))
            minute = int(p.group(2))
            sec = float(p.group(3))
            hemi = p.group(4).upper()
            decimal = _dms_to_decimal(deg, minute, sec, hemi)
            if hemi in ("N", "S"):
                lat = decimal
            else:
                lng = decimal
        if lat is not None and lng is not None and _validate(lat, lng):
            return (lat, lng)

    return None


def format_lat_lng(
    lat: float,
    lng: float,
    decimals: int = DEFAULT_DECIMALS,
) -> str:
    """Format `(lat, lng)` as canonical decimal-degrees string.

    Returns "" for invalid input or negative decimals.
    """
    if not _validate(lat, lng):
        return ""
    if decimals < 0:
        return ""
    return f"{lat:.{decimals}f}, {lng:.{decimals}f}"


def is_in_vietnam(lat: float, lng: float) -> bool:
    """True iff `(lat, lng)` falls within the VN bounding box.

    Sanity-check on uploaded coordinates — defends against typos
    that flip lat/lng or paste a non-VN address into a VN-context
    form.
    """
    if not _validate(lat, lng):
        return False
    return VN_LAT_BAND[0] <= lat <= VN_LAT_BAND[1] and VN_LNG_BAND[0] <= lng <= VN_LNG_BAND[1]
