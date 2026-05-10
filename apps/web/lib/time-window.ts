/**
 * Time-window helpers (cycle Z3, TS half).
 *
 * Today every page with a time-window filter (audit, dead-letter,
 * deliveries, project audit) defines its own `TIME_WINDOWS` array
 * inline. The chip definitions drift — e.g. one page has "1d"
 * where another has "24h"; one page caps at 90, another at 365.
 * This module is the single source of truth.
 *
 *   TIME_WINDOW_OPTIONS  — the canonical chip list
 *   parseSinceDays(v)    — validator matching the API's Query(le=365)
 *   formatRelativeAge    — "23 phút trước" / "3 ngày trước"
 *
 * Pure TS, no React, no DOM access. Drop-in for any chip-driven
 * filter UI.
 *
 * The `since_days` API param is bounded `[1, 365]` server-side
 * (matching `apps/api/services/time_window.py`'s pinned bounds).
 * `null` is the wire-level "no filter" sentinel — pass it through
 * to the API by OMITTING the `since_days` query param entirely.
 */


/** One chip in the time-window picker. `value` is the number of
 *  days for the API; `null` is the "all time" sentinel that
 *  omits the query param entirely. */
export interface TimeWindowOption {
  value: number | null;
  /** UI label — Vietnamese-first per project convention. */
  label: string;
}


/** Canonical chip set used across every page that filters by time
 *  window. Order matters: chips render left-to-right in this
 *  exact sequence so a user moving between pages sees the same
 *  layout. */
export const TIME_WINDOW_OPTIONS: TimeWindowOption[] = [
  { value: 1, label: "24h" },
  { value: 7, label: "7d" },
  { value: 30, label: "30d" },
  { value: null, label: "Tất cả" },
];


/** Server-side cap. Mirrors `apps/api/services/time_window.py`'s
 *  `MAX_SINCE_DAYS` constant. Pass any value above this through
 *  `parseSinceDays` and it clamps / rejects. */
export const MAX_SINCE_DAYS = 365;


/** Default chip when a page first loads. Most users want "last
 *  week" — the cumulative S2/V3 ops dashboards converged on this. */
export const DEFAULT_SINCE_DAYS: number | null = 7;


/**
 * Validate / coerce a since_days input from a query string or
 * other untrusted source.
 *
 *   * `null` / `undefined` → null (the "all time" sentinel).
 *   * Number string ("7") within `[1, MAX_SINCE_DAYS]` → that
 *     number.
 *   * Anything else (negative, zero, > 365, "abc") → null
 *     (graceful fallback to "all time" rather than error).
 *
 * Why graceful fallback rather than throw: a stale URL with an
 * invalid `since_days` would otherwise 500 the page render. The
 * dashboard reads as "no filter" instead — operationally correct.
 */
export function parseSinceDays(input: string | number | null | undefined): number | null {
  if (input === null || input === undefined || input === "") return null;
  const n = typeof input === "number" ? input : Number(input);
  if (!Number.isFinite(n)) return null;
  const integer = Math.trunc(n);
  if (integer < 1 || integer > MAX_SINCE_DAYS) return null;
  return integer;
}


/**
 * Format an ISO-8601 timestamp as "23 phút trước" / "3 giờ trước"
 * / "5 ngày trước" relative to `now`.
 *
 *   * < 60s  → "vừa xong"
 *   * < 60m  → "<N> phút trước"
 *   * < 24h  → "<N> giờ trước"
 *   * < 30d  → "<N> ngày trước"
 *   * < 12mo → "<N> tháng trước"
 *   * else   → "<N> năm trước"
 *
 * Future dates render as "trong tương lai" (clock skew defense).
 * Malformed timestamps return "" so the calling row doesn't crash.
 */
export function formatRelativeAge(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso);
  const ms = d.getTime();
  if (Number.isNaN(ms)) return "";
  const deltaMs = now.getTime() - ms;
  if (deltaMs < 0) return "trong tương lai";
  const seconds = Math.floor(deltaMs / 1000);
  if (seconds < 60) return "vừa xong";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} giờ trước`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} ngày trước`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} tháng trước`;
  const years = Math.floor(days / 365);
  return `${years} năm trước`;
}
