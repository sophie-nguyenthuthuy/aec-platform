/**
 * Webhook delivery sparkline data helper (cycle X3).
 *
 * Takes raw delivery rows (`{created_at, status}`) and produces
 * 7×24 = 168 hourly buckets with `{hour_iso, delivered, failed,
 * pending}` counts. Drives the small sparkline next to T1's
 * health-rate badge so partners see "rate dropped 3 hours ago"
 * at a glance.
 *
 * Why a frontend helper rather than a new backend endpoint:
 *   * The deliveries query at `/webhooks/{id}/deliveries` is
 *     already fetched + cached by the existing detail page.
 *     Bucketing client-side avoids a second round-trip per
 *     subscription render.
 *   * A "give me 168 hourly buckets" backend endpoint would be a
 *     5th delivery-related route (deliveries, dead-letter,
 *     histogram, health) — over-fragmented surface.
 *
 * Bucket alignment: each bucket is keyed by the floored hour in
 * UTC. The 168-bucket window ends at `now`'s current hour
 * (inclusive) and reaches back 167 hours. Pre-window deliveries
 * are silently dropped — the helper assumes the caller passes
 * the right window's deliveries.
 *
 * Pure TS, no DOM, no I/O. Drop-in for any rendered sparkline.
 */


export type DeliveryStatus =
  | "pending"
  | "in_flight"
  | "delivered"
  | "failed";


export interface DeliveryRowLike {
  /** ISO-8601 timestamp; the helper parses via `new Date(...)`. */
  created_at: string;
  status: DeliveryStatus;
}


export interface SparklineBucket {
  /** ISO-8601 timestamp of the bucket's start hour, in UTC. */
  hour_iso: string;
  delivered: number;
  failed: number;
  pending: number; // includes 'pending' AND 'in_flight'
}


/** Total bucket count across the window — 7 days × 24 hours. */
export const SPARKLINE_HOURS = 7 * 24;


/**
 * Build the bucket array for the 7d window ending at `now`.
 *
 * Algorithm:
 *   1. Compute the inclusive end-hour from `now` (floor to hour).
 *   2. Pre-allocate 168 buckets with hour_iso labels descending
 *      from `endHour` to `endHour - 167h`, then reverse so the
 *      array reads left-to-right oldest → newest (sparkline
 *      reading order).
 *   3. Walk deliveries — for each, compute the bucket index by
 *      hour-distance from endHour. Skip if outside [0, 167].
 *   4. Increment the right counter on the bucket.
 *
 * Returns 168 buckets always (filled with zeros where no
 * deliveries land). The spark renders without "missing data"
 * gaps regardless of activity volume.
 */
export function buildSparklineBuckets(
  deliveries: DeliveryRowLike[],
  now: Date = new Date(),
): SparklineBucket[] {
  // Floor `now` to the start of its hour. The end-bucket spans
  // [endHour, endHour + 1h); deliveries within the current hour
  // land in the rightmost bucket.
  const endHour = floorToHour(now);

  // Pre-allocate 168 buckets oldest→newest. `endHour` is the
  // RIGHTMOST bucket's start time.
  const buckets: SparklineBucket[] = [];
  for (let i = SPARKLINE_HOURS - 1; i >= 0; i -= 1) {
    const hourStart = new Date(endHour.getTime() - i * 3600 * 1000);
    buckets.push({
      hour_iso: hourStart.toISOString(),
      delivered: 0,
      failed: 0,
      pending: 0,
    });
  }

  for (const d of deliveries) {
    const ts = new Date(d.created_at);
    if (Number.isNaN(ts.getTime())) continue; // malformed timestamp
    const bucketHour = floorToHour(ts);
    const hoursAgo = Math.round(
      (endHour.getTime() - bucketHour.getTime()) / (3600 * 1000),
    );
    if (hoursAgo < 0 || hoursAgo >= SPARKLINE_HOURS) continue;
    const idx = SPARKLINE_HOURS - 1 - hoursAgo;
    const bucket = buckets[idx];
    if (!bucket) continue;
    if (d.status === "delivered") bucket.delivered += 1;
    else if (d.status === "failed") bucket.failed += 1;
    else bucket.pending += 1; // 'pending' OR 'in_flight'
  }

  return buckets;
}


/** Floor a Date to the start of its UTC hour. Pure helper. */
export function floorToHour(d: Date): Date {
  return new Date(
    Date.UTC(
      d.getUTCFullYear(),
      d.getUTCMonth(),
      d.getUTCDate(),
      d.getUTCHours(),
      0,
      0,
      0,
    ),
  );
}


/**
 * Compute the height of each bar as a fraction of the tallest
 * bucket — used by the sparkline component to size SVG rects.
 *
 * Returns 0 for every bucket when the input is all zeros (avoids
 * a divide-by-zero rendering quirk).
 */
export function bucketHeights(buckets: SparklineBucket[]): number[] {
  const max = buckets.reduce(
    (m, b) => Math.max(m, b.delivered + b.failed + b.pending),
    0,
  );
  if (max === 0) return buckets.map(() => 0);
  return buckets.map(
    (b) => (b.delivered + b.failed + b.pending) / max,
  );
}
