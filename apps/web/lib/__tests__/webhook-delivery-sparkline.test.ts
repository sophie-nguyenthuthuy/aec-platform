/**
 * Webhook delivery sparkline data helper (cycle X3).
 *
 * Pinned seams:
 *   1. Always returns SPARKLINE_HOURS (168) buckets — empty
 *      windows render as a flat baseline rather than gaps.
 *   2. Buckets are ordered oldest → newest (left-to-right read
 *      order for the spark).
 *   3. Hour-floor alignment: a delivery at 12:43 lands in the
 *      12:00 bucket.
 *   4. Out-of-window deliveries are silently dropped.
 *   5. `pending` and `in_flight` collapse into one count (UI
 *      doesn't visually distinguish in-flight from pending).
 *   6. `bucketHeights` returns all-zero when no deliveries
 *      (no divide-by-zero).
 */

import { describe, expect, it } from "vitest";

import {
  SPARKLINE_HOURS,
  bucketHeights,
  buildSparklineBuckets,
  floorToHour,
  type DeliveryRowLike,
} from "../webhook-delivery-sparkline";


// Pin reference time so the bucket math stays deterministic.
const NOW = new Date("2026-05-09T12:43:00Z");


describe("floorToHour", () => {
  it("zeroes out minutes / seconds / milliseconds in UTC", () => {
    const out = floorToHour(new Date("2026-05-09T12:43:17.500Z"));
    expect(out.toISOString()).toBe("2026-05-09T12:00:00.000Z");
  });

  it("preserves the exact UTC hour for a top-of-hour timestamp", () => {
    const out = floorToHour(new Date("2026-05-09T00:00:00.000Z"));
    expect(out.toISOString()).toBe("2026-05-09T00:00:00.000Z");
  });
});


describe("buildSparklineBuckets", () => {
  it("always returns SPARKLINE_HOURS buckets", () => {
    const buckets = buildSparklineBuckets([], NOW);
    expect(buckets).toHaveLength(SPARKLINE_HOURS);
    expect(SPARKLINE_HOURS).toBe(168);
  });

  it("buckets are ordered oldest → newest", () => {
    const buckets = buildSparklineBuckets([], NOW);
    // First bucket = 167h before NOW. Last bucket = NOW's current hour.
    const first = new Date(buckets[0]!.hour_iso).getTime();
    const last = new Date(buckets[buckets.length - 1]!.hour_iso).getTime();
    expect(last - first).toBe(167 * 3600 * 1000);
    expect(buckets[buckets.length - 1]!.hour_iso).toBe("2026-05-09T12:00:00.000Z");
  });

  it("places a delivery in the floored-hour bucket", () => {
    // 12:43 → 12:00 bucket. The current-hour bucket is the last
    // one in the array.
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T12:43:00Z", status: "delivered" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const last = buckets[buckets.length - 1]!;
    expect(last.hour_iso).toBe("2026-05-09T12:00:00.000Z");
    expect(last.delivered).toBe(1);
    expect(last.failed).toBe(0);
    expect(last.pending).toBe(0);
  });

  it("counts failed and delivered separately within the same bucket", () => {
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T12:00:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:30:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:43:00Z", status: "failed" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const last = buckets[buckets.length - 1]!;
    expect(last.delivered).toBe(2);
    expect(last.failed).toBe(1);
  });

  it("collapses 'pending' and 'in_flight' into one bucket count", () => {
    // The UI doesn't distinguish between "queued" and "actively
    // being delivered" — both are "amber" visually.
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T12:10:00Z", status: "pending" },
      { created_at: "2026-05-09T12:20:00Z", status: "in_flight" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const last = buckets[buckets.length - 1]!;
    expect(last.pending).toBe(2);
  });

  it("places a delivery from 3 hours ago in the right bucket", () => {
    // 3h before NOW (12:43) = 09:43 → 09:00 bucket.
    // Bucket index = SPARKLINE_HOURS - 1 - 3 = 164.
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T09:43:00Z", status: "failed" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    expect(buckets[164]!.hour_iso).toBe("2026-05-09T09:00:00.000Z");
    expect(buckets[164]!.failed).toBe(1);
    // The current-hour bucket is unchanged.
    expect(buckets[buckets.length - 1]!.failed).toBe(0);
  });

  it("drops deliveries older than the 7d window", () => {
    // 8 days ago — well outside the 168-hour window. Must be
    // silently dropped (not bucketed at index < 0 / overflow).
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-01T12:00:00Z", status: "delivered" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const totalDelivered = buckets.reduce((s, b) => s + b.delivered, 0);
    expect(totalDelivered).toBe(0);
  });

  it("drops future-dated deliveries (clock skew defense)", () => {
    // A delivery timestamped 1h AFTER NOW shouldn't land in any
    // bucket — there's no "future" bucket in the array. Silently
    // drop rather than overflowing into bucket[167] (which would
    // misleadingly inflate the current-hour count).
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T13:43:00Z", status: "delivered" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const totalDelivered = buckets.reduce((s, b) => s + b.delivered, 0);
    expect(totalDelivered).toBe(0);
  });

  it("ignores deliveries with malformed created_at", () => {
    // Defensive: a row with a non-parseable timestamp doesn't
    // crash the whole sparkline.
    const deliveries: DeliveryRowLike[] = [
      { created_at: "not-a-date", status: "delivered" } as DeliveryRowLike,
      { created_at: "2026-05-09T12:00:00Z", status: "delivered" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    // Only the well-formed delivery counts.
    const totalDelivered = buckets.reduce((s, b) => s + b.delivered, 0);
    expect(totalDelivered).toBe(1);
  });

  it("groups deliveries spanning multiple hours correctly", () => {
    // Three deliveries across the last 3 hours (current + 2 prior).
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T10:30:00Z", status: "delivered" },
      { created_at: "2026-05-09T11:30:00Z", status: "failed" },
      { created_at: "2026-05-09T12:30:00Z", status: "delivered" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    // Hour-2 (10:00 bucket) — index 165
    expect(buckets[165]!.delivered).toBe(1);
    // Hour-1 (11:00 bucket) — index 166
    expect(buckets[166]!.failed).toBe(1);
    // Current hour (12:00 bucket) — index 167
    expect(buckets[167]!.delivered).toBe(1);
  });
});


describe("bucketHeights", () => {
  it("returns all-zero array for empty windows (no divide-by-zero)", () => {
    const buckets = buildSparklineBuckets([], NOW);
    const heights = bucketHeights(buckets);
    expect(heights).toHaveLength(SPARKLINE_HOURS);
    expect(heights.every((h) => h === 0)).toBe(true);
  });

  it("normalises against the tallest bucket", () => {
    // Single bucket with 5 events; everything else 0. The max
    // bucket should be 1.0 and every other bucket 0.0.
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T12:00:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:10:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:20:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:30:00Z", status: "failed" },
      { created_at: "2026-05-09T12:40:00Z", status: "pending" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const heights = bucketHeights(buckets);
    expect(heights[heights.length - 1]).toBe(1);
    // Every prior bucket has zero events → height 0.
    expect(heights.slice(0, -1).every((h) => h === 0)).toBe(true);
  });

  it("scales proportionally for multi-bucket inputs", () => {
    // 4 events in one bucket, 2 events in another. Max=4, so the
    // smaller bucket = 0.5.
    const deliveries: DeliveryRowLike[] = [
      { created_at: "2026-05-09T12:00:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:10:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:20:00Z", status: "delivered" },
      { created_at: "2026-05-09T12:30:00Z", status: "delivered" },
      { created_at: "2026-05-09T11:00:00Z", status: "delivered" },
      { created_at: "2026-05-09T11:30:00Z", status: "delivered" },
    ];
    const buckets = buildSparklineBuckets(deliveries, NOW);
    const heights = bucketHeights(buckets);
    expect(heights[167]).toBe(1); // 4 events
    expect(heights[166]).toBe(0.5); // 2 events
  });
});
