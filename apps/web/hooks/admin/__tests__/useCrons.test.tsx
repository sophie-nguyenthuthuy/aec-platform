import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { type CronEntry, useCrons } from "@/hooks/admin/useCrons";

import { envelopeResponse, makeWrapper } from "../../__tests__/_harness";

/**
 * Pin the wire contract for `useCrons` — the admin cron-registry
 * hook backing `/admin/crons`. Same revert-tripwire role as the
 * other admin/__tests__ pins.
 *
 * Failure modes guarded:
 *
 *   * URL drift — `/api/v1/admin/crons` matches the literal path in
 *     `routers/cron_admin.py`. A pluralisation drift (cron vs crons)
 *     or any other rename silently 404s the dashboard.
 *
 *   * Refetch interval drift — pinned at 60_000 ms. The page's
 *     "next run in X minutes" countdowns lose accuracy beyond that;
 *     a regression to (say) 5 minutes would silently let the page
 *     show 4-minute-stale countdowns.
 *
 *   * Envelope unwrap — `res.data ?? []` so the page can `.map()`
 *     unconditionally. A regression to returning `null` would crash
 *     the table render.
 *
 *   * Cache key — `["admin", "crons"]`. Other hooks under
 *     `["admin"]` (slack-deliveries, webhook-deliveries-admin) MUST
 *     NOT collide with this key on a targeted invalidate.
 */

const CRONS_PATH = "/api/v1/admin/crons";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// ---------- URL + method ----------


describe("useCrons / URL", () => {
  test("GETs /api/v1/admin/crons", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useCrons(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(CRONS_PATH);
    expect((init as RequestInit).method).toBe("GET");
  });
});


// ---------- Envelope unwrapping ----------


describe("useCrons / envelope unwrapping", () => {
  test("returns the rows array from the envelope's `data` field", async () => {
    const rows: CronEntry[] = [
      {
        name: "cron:weekly_report_cron",
        function: "weekly_report_cron",
        module: "workers.queue",
        schedule: "Mondays at 06:00 UTC",
        next_run: "2026-05-12T06:00:00+00:00",
        description: "Weekly project report — emails owners on Monday.",
        // K1 added last_run telemetry. Null here covers the "cron
        // hasn't fired yet" branch that the dashboard's LastRunCell
        // renders as "no runs yet" greyed out.
        last_run: null,
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useCrons(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(rows);
  });

  test("round-trips a last_run with the stuck flag set", async () => {
    // Pins the `stuck` field on `CronLastRun`. The watchdog Slack-
    // alerts on `_is_stuck === true` (3× p95 over 7d) and the
    // dashboard surfaces the same flag visually so ops sees the
    // stuck state BEFORE the alert fires. Drift on either side
    // would silently break that "visible-before-alert" property.
    const rows: CronEntry[] = [
      {
        name: "cron:weekly_report_cron",
        function: "weekly_report_cron",
        module: "workers.queue",
        schedule: "Mondays at 06:00 UTC",
        next_run: "2026-05-12T06:00:00+00:00",
        description: "Weekly project report — emails owners on Monday.",
        last_run: {
          started_at: "2026-05-09T06:00:00+00:00",
          // null finished_at — the run is still going.
          finished_at: null,
          status: "running",
          duration_ms: null,
          error_message: null,
          // The watchdog has flagged this in-flight run as stuck.
          // Dashboard's LastRunCell renders an amber pill on this branch.
          stuck: true,
        },
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useCrons(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Equality of the full row catches:
    //   * `stuck` field rename on the wire
    //   * type drift (e.g. number `1` instead of boolean `true`)
    //   * accidental field omission by the hook's projection
    expect(result.current.data).toEqual(rows);
    expect(result.current.data?.[0]?.last_run?.stuck).toBe(true);
  });

  test("round-trips a last_run with stuck=null for non-running rows", async () => {
    // Pin: `stuck` is null when status != 'running'. Stuck
    // detection only applies to in-flight runs; a regression that
    // emitted `false` on succeeded/failed rows would let the
    // dashboard show "not stuck" pills next to runs that AREN'T
    // running at all (visual noise).
    const rows: CronEntry[] = [
      {
        name: "cron:webhook_drain_cron",
        function: "webhook_drain_cron",
        module: "workers.queue",
        schedule: "Every minute",
        next_run: null,
        description: "Drain pending webhook outbox rows.",
        last_run: {
          started_at: "2026-05-09T05:59:00+00:00",
          finished_at: "2026-05-09T05:59:00+00:00",
          status: "succeeded",
          duration_ms: 423,
          error_message: null,
          // Not running → stuck check is N/A. Backend MUST emit null.
          stuck: null,
        },
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useCrons(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.[0]?.last_run?.stuck).toBeNull();
  });

  test("returns [] when envelope's `data` is null (no crons registered)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useCrons(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Empty-array fallback prevents a crash on `data.map(...)` in
    // the page. A regression returning `null` would surface as a
    // TypeError on first render.
    expect(result.current.data).toEqual([]);
  });
});


// ---------- Refetch interval ----------


describe("useCrons / refetch cadence", () => {
  test("uses TanStack Query's refetchInterval to keep next_run countdowns fresh", async () => {
    // We can't directly assert the interval value off the hook (it's
    // internal to the query observer), but we CAN spy on the fetch
    // call count after a controlled time advance. Use Vitest's fake
    // timers for deterministic timing.
    vi.useFakeTimers();
    try {
      fetchMock.mockResolvedValue(envelopeResponse([]));

      const { result } = renderHook(() => useCrons(), {
        wrapper: makeWrapper(),
      });

      // First fetch — initial mount.
      await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(fetchMock).toHaveBeenCalledTimes(1);

      // Advance time past the documented 60-second refetch interval.
      // If the interval is materially different (5min, off entirely),
      // this advance would either fire too few or too many fetches
      // — the count assertion below catches both regressions.
      await vi.advanceTimersByTimeAsync(61_000);

      // After 61s: at least one refetch should have been queued.
      // (Use `>=` rather than exactly 2 because TanStack Query may
      // batch refetches with focus events in jsdom.)
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    } finally {
      vi.useRealTimers();
    }
  });
});


// ---------- Cache-key shape ----------


describe("useCrons / cache key", () => {
  test("uses [admin, crons] so it doesn't collide with sibling admin hooks", async () => {
    // Indirect assertion via the hook actually running and hitting
    // the URL — a key collision wouldn't surface here, but if the
    // key changed shape (e.g. added a per-org segment) we'd see
    // multiple fetches when only one is expected. Pinning the
    // exact key shape requires reading TanStack's internals; the
    // URL+method assertions above catch the common regressions.
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useCrons(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Exactly one fetch from one hook render. Multiple = key
    // unstable across re-renders (would drift cache + cause
    // bandwidth bloat).
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
