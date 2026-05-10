/**
 * Date range parser (cycle JJ2, TS half).
 *
 * Parse URL filter query params `?from=2026-01-01&to=2026-02-01`
 * (or relative `?from=7d&to=now`) into a structured date range.
 * Used by the audit page filter, deliveries page filter, and
 * dead-letter filter. Today each duplicates the parsing inline
 * with subtly different MAX_RANGE clamping. This module is the
 * single source of truth.
 *
 *   parseDateRange(from, to, todayIso) — DateRange or null
 *   MAX_RANGE_DAYS                     — 365
 *
 * Date format: ISO `YYYY-MM-DD` strings throughout (no Date
 * objects exposed — frees the caller from timezone footguns).
 *
 * Closed-interval semantics:
 *   * `start` is INCLUSIVE.
 *   * `end` is INCLUSIVE.
 *   Pin: this differs from II1's audit-search half-open `since`.
 *   Documented because callers use the result to build SQL
 *   `BETWEEN` (inclusive) clauses.
 *
 * One-sided ranges allowed:
 *   * `from=7d` only → range from 7 days ago to today.
 *   * `to=2026-01-01` only → range from MAX_RANGE_DAYS ago to that date.
 *
 * Pure TS. Mirrors `apps/api/services/date_range.py`.
 */


/** Maximum range size. Defends against `from=2000-01-01&to=now`
 *  parking the audit query for years. Pin so a bump surfaces. */
export const MAX_RANGE_DAYS = 365;


export interface DateRange {
  /** ISO YYYY-MM-DD, inclusive. */
  start: string;
  /** ISO YYYY-MM-DD, inclusive. */
  end: string;
}


const _MS_PER_DAY = 86400000;
const _REL_DAYS_RE = /^(\d+)d$/;
const _ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;


function _parseIsoToUtcMs(iso: string): number | null {
  const m = _ISO_DATE_RE.exec(iso);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const ms = Date.UTC(year, month - 1, day);
  // Validate roundtrip (catches 2026-02-31 etc).
  const d = new Date(ms);
  if (
    d.getUTCFullYear() !== year ||
    d.getUTCMonth() !== month - 1 ||
    d.getUTCDate() !== day
  ) {
    return null;
  }
  return ms;
}


function _msToIso(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}


function _parseDateValue(
  value: string,
  todayMs: number,
): number | null {
  const s = value.trim().toLowerCase();
  if (!s) return null;
  if (s === "now") return todayMs;
  const rel = _REL_DAYS_RE.exec(s);
  if (rel) {
    const n = Number(rel[1]);
    if (n >= 1 && n <= MAX_RANGE_DAYS) {
      return todayMs - n * _MS_PER_DAY;
    }
    return null;
  }
  return _parseIsoToUtcMs(s);
}


/**
 * Parse `from`/`to` URL params into a DateRange (or null).
 *
 * Both ends optional but at least one required. `todayIso` is
 * required (caller passes `today` explicitly for testability).
 *
 * Returns null when:
 *   * Both `from` and `to` are null/undefined/empty.
 *   * Either value is malformed.
 *   * Resolved start > resolved end.
 *   * Resolved range exceeds MAX_RANGE_DAYS.
 */
export function parseDateRange(
  fromValue: string | null | undefined,
  toValue: string | null | undefined,
  todayIso: string,
): DateRange | null {
  const todayMs = _parseIsoToUtcMs(todayIso);
  if (todayMs === null) return null;

  const hasFrom = fromValue !== null && fromValue !== undefined && fromValue !== "";
  const hasTo = toValue !== null && toValue !== undefined && toValue !== "";

  if (!hasFrom && !hasTo) return null;

  let startMs: number;
  if (hasFrom) {
    const parsed = _parseDateValue(fromValue!, todayMs);
    if (parsed === null) return null;
    startMs = parsed;
  } else {
    startMs = todayMs - MAX_RANGE_DAYS * _MS_PER_DAY;
  }

  let endMs: number;
  if (hasTo) {
    const parsed = _parseDateValue(toValue!, todayMs);
    if (parsed === null) return null;
    endMs = parsed;
  } else {
    endMs = todayMs;
  }

  if (startMs > endMs) return null;

  const diffDays = Math.round((endMs - startMs) / _MS_PER_DAY);
  if (diffDays > MAX_RANGE_DAYS) return null;

  return {
    start: _msToIso(startMs),
    end: _msToIso(endMs),
  };
}
