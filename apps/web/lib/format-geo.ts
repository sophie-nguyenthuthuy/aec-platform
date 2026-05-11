/**
 * Geographic coordinate parser/formatter (cycle TT1, TS half).
 *
 * Parse and format GPS coordinates for project locations, RFQ
 * delivery addresses, and audit row geo-impact rows. Today the
 * project location form, the map widget, and the audit row's
 * coordinate display each parse inline with subtly different
 * format support. This module is the single source of truth.
 *
 *   parseLatLng(input)              — [lat, lng] or null
 *   formatLatLng(lat, lng, decimals) — "21.028500, 105.854200" or ""
 *   isInVietnam(lat, lng)            — bool
 *
 * Pure TS. Mirrors `apps/api/services/format_geo.py`.
 *
 * Pinned invariants:
 *   * Lat ∈ [-90, 90]; lng ∈ [-180, 180]; out → null/"".
 *   * Decimal degrees AND DMS notation accepted on parse.
 *   * DMS hemisphere letters (N/S/E/W) flip sign.
 *   * Default 6 decimals on format (~0.1m precision at equator).
 *   * JS-compatible half-up rounding (matches AA1/NN3/SS3 pattern).
 *   * Cross-language byte-for-byte parity for canonical decimal cases.
 */


export const LAT_MIN = -90;
export const LAT_MAX = 90;
export const LNG_MIN = -180;
export const LNG_MAX = 180;
export const DEFAULT_DECIMALS = 6;


/** Approximate VN bounding box. Used for the optional
 *  "is this in Vietnam?" sanity check on uploaded coordinates. */
export const VN_LAT_BAND: readonly [number, number] = [8.0, 24.0];
export const VN_LNG_BAND: readonly [number, number] = [102.0, 110.0];


// "21.0285, 105.8542" or "21.0285,105.8542" or "21.0285 105.8542"
const _DECIMAL_PAIR_RE = /^\s*([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)\s*$/;

// `21°01'42.6"N` style DMS piece.
const _DMS_PIECE_RE = /(\d+)\s*°\s*(\d+)\s*'\s*(\d+(?:\.\d+)?)\s*"?\s*([NSEW])/gi;


function _validate(lat: number, lng: number): boolean {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return false;
  return lat >= LAT_MIN && lat <= LAT_MAX && lng >= LNG_MIN && lng <= LNG_MAX;
}


function _dmsToDecimal(
  deg: number,
  min: number,
  sec: number,
  hemi: string,
): number {
  const decimal = deg + min / 60 + sec / 3600;
  return hemi.toUpperCase() === "S" || hemi.toUpperCase() === "W"
    ? -decimal
    : decimal;
}


/**
 * Parse a coordinate pair string.
 *
 *   * parseLatLng("21.0285, 105.8542")     → [21.0285, 105.8542]
 *   * parseLatLng("-21.0285, -105.8542")   → [-21.0285, -105.8542]
 *   * parseLatLng("21°01'42.6\"N 105°51'15.1\"E") → [~21.0285, ~105.8542]
 *   * parseLatLng("91, 0")                 → null  (lat out of range)
 *   * parseLatLng("not-coords")            → null
 *   * parseLatLng(null)                    → null
 */
export function parseLatLng(
  input: string | null | undefined,
): [number, number] | null {
  if (!input) return null;
  const s = input.trim();
  if (!s) return null;

  // Try decimal pair.
  const decimalMatch = _DECIMAL_PAIR_RE.exec(s);
  if (decimalMatch) {
    const lat = parseFloat(decimalMatch[1]!);
    const lng = parseFloat(decimalMatch[2]!);
    if (_validate(lat, lng)) return [lat, lng];
    return null;
  }

  // Try DMS pair.
  const pieces: RegExpMatchArray[] = [];
  let m: RegExpExecArray | null;
  // Reset lastIndex since we're sharing a global regex.
  _DMS_PIECE_RE.lastIndex = 0;
  while ((m = _DMS_PIECE_RE.exec(s)) !== null) {
    pieces.push(m);
  }
  if (pieces.length === 2) {
    let lat: number | null = null;
    let lng: number | null = null;
    for (const p of pieces) {
      const deg = parseInt(p[1]!, 10);
      const min = parseInt(p[2]!, 10);
      const sec = parseFloat(p[3]!);
      const hemi = p[4]!.toUpperCase();
      const decimal = _dmsToDecimal(deg, min, sec, hemi);
      if (hemi === "N" || hemi === "S") lat = decimal;
      else lng = decimal;
    }
    if (lat !== null && lng !== null && _validate(lat, lng)) {
      return [lat, lng];
    }
  }

  return null;
}


/**
 * Format a lat/lng as canonical decimal-degrees string.
 *
 *   * formatLatLng(21.0285, 105.8542)    → "21.028500, 105.854200"
 *   * formatLatLng(21.0285, 105.8542, 4) → "21.0285, 105.8542"
 *   * formatLatLng(91, 0)                → ""  (out of range)
 */
export function formatLatLng(
  lat: number,
  lng: number,
  decimals: number = DEFAULT_DECIMALS,
): string {
  if (!_validate(lat, lng)) return "";
  if (decimals < 0) return "";
  return `${lat.toFixed(decimals)}, ${lng.toFixed(decimals)}`;
}


/** True iff `(lat, lng)` falls within the approximate VN
 *  bounding box. Used as a sanity-check on uploaded
 *  coordinates — defends against typos that flip lat/lng
 *  or paste a non-VN address into a VN-context form. */
export function isInVietnam(lat: number, lng: number): boolean {
  if (!_validate(lat, lng)) return false;
  return (
    lat >= VN_LAT_BAND[0] &&
    lat <= VN_LAT_BAND[1] &&
    lng >= VN_LNG_BAND[0] &&
    lng <= VN_LNG_BAND[1]
  );
}
