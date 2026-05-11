import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  adminKeys,
  useScraperRuns,
  useScraperRunsSummary,
} from "@/hooks/admin/useScraperRuns";

import { envelopeResponse, makeWrapper } from "../../__tests__/_harness";

/**
 * Pin the wire contract for the older admin scraper-runs hooks.
 *
 * Why this exists now: the newer admin hooks (`useSlackDeliveries`,
 * `useWebhookDeliveriesAdmin`) shipped with vitest pins. The older
 * `useScraperRuns` + `useScraperRunsSummary` (and their shared
 * `adminKeys` namespace) didn't — leaving the most-used admin
 * dashboard's data layer with no tripwire.
 *
 * That asymmetry matters because the scraper-runs page is the most-
 * opened admin surface in production (drift triage is a weekly
 * activity for ops). A typo in the URL or a query-key collision
 * with the new admin hooks would render the dashboard blank with
 * no error visible — exactly the silent-break failure mode the
 * pin pattern catches.
 *
 * What this catches:
 *
 *   * URL drift on `GET /api/v1/admin/scraper-runs` and
 *     `/api/v1/admin/scraper-runs/summary`.
 *   * Query-string param drift — `slug`, `limit`, `days` are the
 *     three filters that drive the dashboard's window controls.
 *   * `adminKeys.scraperRuns(...)` and `.scraperRunsSummary(...)`
 *     produce DIFFERENT keys per filter (otherwise stale data
 *     bleeds between window-toggle clicks).
 *   * `adminKeys.all === ["admin"]` — shared root with the newer
 *     hooks. A rename here would break a top-level invalidate of
 *     `["admin"]` (rare; debug only) but pin it for predictability.
 *   * Envelope unwrap — `null data → []` so consumers can `.map()`
 *     unconditionally.
 */

const RUNS_PATH = "/api/v1/admin/scraper-runs";
const SUMMARY_PATH = "/api/v1/admin/scraper-runs/summary";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// ---------- URL + method ----------


describe("useScraperRuns / URL", () => {
  test("GETs the documented admin path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useScraperRuns(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(RUNS_PATH);
    expect((init as RequestInit).method ?? "GET").toBe("GET");
  });

  test("default limit is 20 (matches the dashboard's first page)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useScraperRuns(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("limit")).toBe("20");
  });

  test("forwards `slug` and `limit` as query params", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useScraperRuns({ slug: "hanoi", limit: 50 }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    const params = new URL(url as string).searchParams;
    expect(params.get("slug")).toBe("hanoi");
    expect(params.get("limit")).toBe("50");
  });
});


describe("useScraperRunsSummary / URL", () => {
  test("GETs the summary path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useScraperRunsSummary(30), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(SUMMARY_PATH);
  });

  test("encodes `days` as a query param (server validates 1..365)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useScraperRunsSummary(7), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("days")).toBe("7");
  });

  test("default days is 30", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useScraperRunsSummary(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("days")).toBe("30");
  });
});


// ---------- Query-key shape ----------


describe("adminKeys / scraper-runs namespacing", () => {
  test("adminKeys.all is exactly [admin]", () => {
    // Shared root with `slackDeliveriesKeys.all` +
    // `webhookDeliveriesAdminKeys.all`. A rename here would break
    // a top-level invalidate of `["admin"]` (debug-only path) but
    // also make the discriminator inconsistent. Pin the literal.
    expect(adminKeys.all).toEqual(["admin"]);
  });

  test("scraperRuns and scraperRunsSummary use different discriminators", () => {
    // If both used the same discriminator string, an invalidate of
    // one would trash the other's cache. Pin the discriminator
    // strings explicitly.
    const runs = adminKeys.scraperRuns();
    const summary = adminKeys.scraperRunsSummary();

    expect(runs[1]).toBe("scraper-runs");
    expect(summary[1]).toBe("scraper-runs-summary");
  });

  test("scraper-runs keys do NOT collide with slack/webhook deliveries", () => {
    // The newer admin hooks live under `["admin", "slack-deliveries"]`
    // and `["admin", "webhook-deliveries"]`. A regression that
    // renamed the scrapers discriminator to one of those would
    // collide caches.
    const runs = adminKeys.scraperRuns();
    expect(runs[1]).not.toBe("slack-deliveries");
    expect(runs[1]).not.toBe("webhook-deliveries");
  });

  test("scraperRuns keys vary on slug + limit", () => {
    // Two filter combos MUST produce different keys; otherwise
    // TanStack Query serves stale data after a slug/limit change.
    const fingerprints = new Set(
      [
        adminKeys.scraperRuns(undefined, 20),
        adminKeys.scraperRuns("hanoi", 20),
        adminKeys.scraperRuns(undefined, 50),
        adminKeys.scraperRuns("hanoi", 50),
      ].map((k) => JSON.stringify(k)),
    );
    expect(fingerprints.size).toBe(4);
  });

  test("scraperRunsSummary varies on `days`", () => {
    const week = adminKeys.scraperRunsSummary(7);
    const month = adminKeys.scraperRunsSummary(30);
    expect(JSON.stringify(week)).not.toBe(JSON.stringify(month));
  });

  test("default-arg key matches explicit-arg key (window 30, limit 20)", () => {
    // The hook's default refers to `limit=20` / `days=30`; the key
    // builder should produce the SAME key for the default-arg call
    // as for an explicit `limit=20` / `days=30` call. Otherwise a
    // page mounting both flavours of caller would double-fetch.
    expect(JSON.stringify(adminKeys.scraperRuns())).toBe(
      JSON.stringify(adminKeys.scraperRuns(undefined, 20)),
    );
    expect(JSON.stringify(adminKeys.scraperRunsSummary())).toBe(
      JSON.stringify(adminKeys.scraperRunsSummary(30)),
    );
  });
});


// ---------- Envelope unwrapping ----------


describe("useScraperRuns / envelope unwrapping", () => {
  test("returns the rows array from the envelope's data field", async () => {
    const rows = [
      {
        id: "00000000-0000-0000-0000-000000000001",
        slug: "hanoi",
        started_at: "2026-05-05T12:00:00Z",
        ok: true,
        scraped: 100,
        unmatched: 5,
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useScraperRuns(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(rows);
  });

  test("returns [] when envelope's data is null", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useScraperRuns(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // `null → []` normalisation matters because the dashboard
    // calls `.map((row) => ...)` unconditionally — `null` would
    // crash the render.
    expect(result.current.data).toEqual([]);
  });
});
