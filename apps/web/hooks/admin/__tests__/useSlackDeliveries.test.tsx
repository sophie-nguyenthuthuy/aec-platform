import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  slackDeliveriesKeys,
  useSlackDeliveries,
  useSlackDeliveriesSummary,
} from "@/hooks/admin/useSlackDeliveries";

import { envelopeResponse, makeWrapper } from "../../__tests__/_harness";

/**
 * Pin the wire contract for the Slack-deliveries admin hooks.
 *
 * What can silently break here:
 *
 *   * URL drift — a typo in the path means the hook 404s and the
 *     dashboard renders an empty state forever (the empty state
 *     looks identical to "no slack deliveries yet", so the bug
 *     hides).
 *
 *   * Tri-state `delivered` filter — the documented behaviour is
 *     `undefined` → omit param (return all rows), `true` / `false`
 *     → filter to that outcome. A regression that sends `delivered=null`
 *     would coerce server-side and silently filter out the
 *     delivered rows.
 *
 *   * Query-key shape — `["admin", "slack-deliveries", ...]` is a
 *     superset of `["admin"]`. A future cache-invalidate of the
 *     scrapers feed (`["admin", "scraper-runs"]`) MUST NOT touch
 *     these caches; pin the discriminator.
 *
 * These are the kind of bugs that don't show up until ops opens
 * the dashboard during an incident — exactly the wrong moment to
 * find a silent failure. Pin everything that's prone to typo.
 */

const SLACK_LIST_PATH = "/api/v1/admin/slack-deliveries";
const SLACK_SUMMARY_PATH = "/api/v1/admin/slack-deliveries/summary";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// ---------- URL + method ----------


describe("useSlackDeliveries / URL", () => {
  test("GETs the documented admin path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useSlackDeliveries(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(SLACK_LIST_PATH);
    expect((init as RequestInit).method ?? "GET").toBe("GET");
  });
});


describe("useSlackDeliveriesSummary / URL", () => {
  test("GETs the documented summary path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useSlackDeliveriesSummary(7), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(SLACK_SUMMARY_PATH);
  });

  test("encodes `days` as a query param (the server validates 1..365)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useSlackDeliveriesSummary(30), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("days")).toBe("30");
  });
});


// ---------- Tri-state `delivered` filter ----------


describe("useSlackDeliveries / delivered filter is tri-state", () => {
  test("omits the `delivered` param entirely when undefined", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useSlackDeliveries(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    // CRITICAL: must NOT appear in the search string at all.
    // Sending `delivered=null` or `delivered=` would coerce server-
    // side and silently filter out the delivered rows.
    expect(new URL(url as string).searchParams.has("delivered")).toBe(false);
  });

  test("sends `delivered=true` when caller asks for delivered-only", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useSlackDeliveries({ delivered: true }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("delivered")).toBe("true");
  });

  test("sends `delivered=false` when caller asks for failures-only", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useSlackDeliveries({ delivered: false }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    // The dashboard's "show only failures" toggle uses this branch —
    // a regression here would render the same data as "all attempts"
    // and the toggle would do nothing visible.
    expect(new URL(url as string).searchParams.get("delivered")).toBe("false");
  });
});


// ---------- Kind filter + limit ----------


describe("useSlackDeliveries / kind + limit pass-through", () => {
  test("forwards `kind` and `limit` as query params", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useSlackDeliveries({ kind: "scraper_drift", limit: 25 }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    const params = new URL(url as string).searchParams;
    expect(params.get("kind")).toBe("scraper_drift");
    expect(params.get("limit")).toBe("25");
  });

  test("default limit is 50 (matches the dashboard's first page size)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useSlackDeliveries(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("limit")).toBe("50");
  });
});


// ---------- Query-key shape ----------


describe("slackDeliveriesKeys / namespacing", () => {
  test("all keys live under [admin, slack-deliveries]", () => {
    // A top-level invalidate of `[admin, slack-deliveries]` should
    // wipe every cached query for this surface; pin the prefix so
    // a key rename doesn't silently break that.
    const list = slackDeliveriesKeys.list();
    const summary = slackDeliveriesKeys.summary();

    expect(list.slice(0, 2)).toEqual(["admin", "slack-deliveries"]);
    expect(summary.slice(0, 2)).toEqual(["admin", "slack-deliveries"]);
  });

  test("list and summary are separately addressable (different 3rd segment)", () => {
    // If both used the same discriminator, an invalidate of one
    // would trash the other's cache. Pin the discriminator
    // (`"list"` vs `"summary"`) so they stay separable.
    const list = slackDeliveriesKeys.list();
    const summary = slackDeliveriesKeys.summary();

    expect(list[2]).toBe("list");
    expect(summary[2]).toBe("summary");
  });

  test("list keys vary on each filter so cached entries don't collide", () => {
    // Two calls with different filters MUST produce different
    // keys — otherwise TanStack Query serves stale data from a
    // sibling filter. Tri-state `delivered` is the trickiest one;
    // pin all three branches.
    const all = slackDeliveriesKeys.list(undefined, undefined, 50);
    const onlyKind = slackDeliveriesKeys.list("scraper_drift", undefined, 50);
    const onlyDelivered = slackDeliveriesKeys.list(undefined, true, 50);
    const onlyFailed = slackDeliveriesKeys.list(undefined, false, 50);

    const fingerprints = new Set(
      [all, onlyKind, onlyDelivered, onlyFailed].map((k) => JSON.stringify(k)),
    );
    expect(fingerprints.size).toBe(4);
  });

  test("summary varies on `days` so different windows don't collide", () => {
    const week = slackDeliveriesKeys.summary(7);
    const month = slackDeliveriesKeys.summary(30);

    expect(JSON.stringify(week)).not.toBe(JSON.stringify(month));
  });
});


// ---------- Envelope unwrapping ----------


describe("useSlackDeliveries / envelope unwrapping", () => {
  test("returns the rows array from the envelope's `data` field", async () => {
    const rows = [
      {
        id: "00000000-0000-0000-0000-000000000001",
        kind: "scraper_drift",
        delivered: false,
        reason: "transport:TimeoutException",
        status_code: null,
        text_preview: "Drift threshold breached on `vatlieuxaydung`",
        created_at: "2026-05-05T12:00:00Z",
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useSlackDeliveries(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(rows);
  });

  test("returns [] when envelope's `data` is null (empty admin list)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useSlackDeliveries(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // The hook normalises `null → []` so consumers can `.map()`
    // unconditionally. A regression that returned `null` would
    // crash the dashboard's `.map((d) => ...)` render.
    expect(result.current.data).toEqual([]);
  });
});
