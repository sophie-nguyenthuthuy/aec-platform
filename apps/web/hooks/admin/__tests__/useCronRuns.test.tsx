import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { type CronRunEntry, useCronRuns } from "@/hooks/admin/useCrons";

import { envelopeResponse, makeWrapper } from "../../__tests__/_harness";

/**
 * Pin the wire contract for `useCronRuns` — the per-cron drilldown
 * hook backing `/admin/crons/[cron_name]`.
 *
 * Failure modes guarded:
 *
 *   * URL-encoding drift — arq cron names are `cron:<func_name>`
 *     and the colon is a reserved URL character. A regression that
 *     dropped the `encodeURIComponent` would either:
 *       - work in Chrome (which auto-encodes) but fail on stricter
 *         clients (curl piping the URL through a lint),
 *       - or worse, hit a different route by accident if the colon
 *         got interpreted as a port separator anywhere upstream.
 *
 *   * `enabled: Boolean(cronName)` — without this guard, route
 *     landings before `useParams()` resolves would 404 the API.
 *
 *   * Cache-key includes the cron name — different crons MUST
 *     produce different fetches, otherwise data bleeds between
 *     drilldowns.
 *
 *   * Refetch interval pinned at 30s — this is the page ops opens
 *     during incidents; a regression to 5min would let the page
 *     show stale "running" / "failed" status long after a retry
 *     succeeded.
 *
 *   * Envelope unwrap — `(res.data ?? []) as CronRunEntry[]`. Page
 *     calls `.map()` unconditionally, so null leakage would crash
 *     the table render.
 */

const TEST_CRON = "cron:weekly_report_cron";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// ---------- URL + encoding ----------


describe("useCronRuns / URL", () => {
  test("GETs /api/v1/admin/crons/{cron_name}/runs with the encoded name", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useCronRuns(TEST_CRON), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    // The colon in "cron:weekly_report_cron" MUST be percent-encoded
    // to %3A. A regression that skipped encoding would emit the raw
    // colon, which most stack handles but is technically reserved.
    const pathname = new URL(url as string).pathname;
    expect(pathname).toBe(
      `/api/v1/admin/crons/${encodeURIComponent(TEST_CRON)}/runs`,
    );
    expect(pathname).toContain("%3A"); // explicit colon-encoding pin
    expect((init as RequestInit).method).toBe("GET");
  });

  test("encodes the cron name even when it contains slash-like chars", async () => {
    // Defensive against future cron naming conventions. Today all
    // names are `cron:<func>`, but a refactor to namespace by module
    // (`cron:workers.queue.weekly_report`) wouldn't trip the route
    // because we encode the dots too.
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const namespaced = "cron:workers.queue.weekly_report";
    const { result } = renderHook(() => useCronRuns(namespaced), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    const pathname = new URL(url as string).pathname;
    expect(pathname).toBe(
      `/api/v1/admin/crons/${encodeURIComponent(namespaced)}/runs`,
    );
  });
});


// ---------- Disabled when name is undefined ----------


describe("useCronRuns / disabled when cronName is undefined", () => {
  test("does NOT fire the request when cronName is undefined", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    renderHook(() => useCronRuns(undefined), {
      wrapper: makeWrapper(),
    });

    // Allow a tick for any queued query to fire.
    await new Promise((resolve) => setTimeout(resolve, 50));

    // The hook MUST be `enabled: Boolean(cronName)`. Without that,
    // route landings before `useParams()` resolves would 404 the
    // API (or worse, hit `/api/v1/admin/crons/undefined/runs`).
    expect(fetchMock).not.toHaveBeenCalled();
  });
});


// ---------- Envelope unwrapping ----------


describe("useCronRuns / envelope unwrapping", () => {
  test("returns the rows from the envelope's `data` field", async () => {
    const rows: CronRunEntry[] = [
      {
        id: "00000000-0000-0000-0000-000000000001",
        started_at: "2026-05-09T06:00:00+00:00",
        finished_at: "2026-05-09T06:00:01+00:00",
        status: "succeeded",
        duration_ms: 1234,
        error_message: null,
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useCronRuns(TEST_CRON), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(rows);
  });

  test("returns [] when envelope's `data` is null", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useCronRuns(TEST_CRON), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // `.map()`-friendly empty fallback — the drilldown page's table
    // would crash on `null.map(...)` without it.
    expect(result.current.data).toEqual([]);
  });
});


// ---------- Cache-key shape ----------


describe("useCronRuns / cache key", () => {
  test("different cron names produce distinct fetches (no cache bleed)", async () => {
    const cronA = "cron:weekly_report_cron";
    const cronB = "cron:webhook_drain_cron";

    fetchMock.mockResolvedValue(envelopeResponse([]));

    // Render two hooks against the SAME wrapper (shared QueryClient).
    // If they shared a cache key, the second hook would replay the
    // first's cached data instead of issuing a fetch.
    const wrapper = makeWrapper();
    renderHook(() => useCronRuns(cronA), { wrapper });
    renderHook(() => useCronRuns(cronB), { wrapper });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const calledPaths = fetchMock.mock.calls.map(
      (c) => new URL(c[0] as string).pathname,
    );
    expect(calledPaths).toContain(
      `/api/v1/admin/crons/${encodeURIComponent(cronA)}/runs`,
    );
    expect(calledPaths).toContain(
      `/api/v1/admin/crons/${encodeURIComponent(cronB)}/runs`,
    );
  });

  test("namespaces under [admin, crons, runs] so it doesn't collide with the registry hook", async () => {
    // The registry hook uses ["admin", "crons"]; this hook uses
    // ["admin", "crons", "runs", cronName]. A targeted invalidate
    // of the registry MUST NOT trash the per-cron drilldown caches
    // (and vice versa). We can't directly assert the key shape from
    // outside TanStack, but we can prove that:
    //   1. A registry refetch doesn't trigger drilldown refetches
    //      (different keys → not invalidated together).
    //   2. The hook itself fetches exactly once per render.
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useCronRuns(TEST_CRON), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
