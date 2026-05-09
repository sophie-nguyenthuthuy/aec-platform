import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  useWebhookDeliveriesAdmin,
  useWebhookDeliveriesAdminSummary,
  useWebhookDeliveryAdminDetail,
  webhookDeliveriesAdminKeys,
} from "@/hooks/admin/useWebhookDeliveriesAdmin";

import { envelopeResponse, makeWrapper } from "../../__tests__/_harness";

/**
 * Pin the wire contract for the platform-admin webhook-deliveries
 * hooks. Same revert-tripwire role as
 * `useSlackDeliveries.test.tsx`.
 *
 * What this catches:
 *
 *   * URL drift — a typo in the path means the hook 404s and the
 *     dashboard renders an empty state forever (visually
 *     indistinguishable from "no webhook deliveries this week",
 *     so the bug hides).
 *
 *   * Tri-state filter semantics — `status === undefined` MUST
 *     omit the param entirely. Sending `status=null` would fail
 *     the server's enum validation with a 400, breaking the
 *     "all statuses" default view.
 *
 *   * Query-key namespacing under `["admin", "webhook-deliveries"]`
 *     so it doesn't collide with the slack-deliveries keys (which
 *     also live under `["admin"]`).
 *
 *   * Filter-vary — different filters MUST produce different cache
 *     keys (otherwise stale data bleeds across filter toggles).
 */

const LIST_PATH = "/api/v1/admin/webhook-deliveries";
const SUMMARY_PATH = "/api/v1/admin/webhook-deliveries/summary";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// ---------- URL + method ----------


describe("useWebhookDeliveriesAdmin / URL", () => {
  test("GETs the documented admin path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useWebhookDeliveriesAdmin(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(LIST_PATH);
    expect((init as RequestInit).method ?? "GET").toBe("GET");
  });
});


describe("useWebhookDeliveriesAdminSummary / URL", () => {
  test("GETs the documented summary path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useWebhookDeliveriesAdminSummary(7), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(SUMMARY_PATH);
  });

  test("encodes `days` (server validates 1..90)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useWebhookDeliveriesAdminSummary(7), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("days")).toBe("7");
  });
});


// ---------- Tri-state status filter ----------


describe("useWebhookDeliveriesAdmin / status filter is tri-state", () => {
  test("omits the `status` param entirely when undefined", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useWebhookDeliveriesAdmin(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    // CRITICAL: must NOT appear in the search string at all.
    // The server's enum validation would 400 on a literal "null"
    // string, breaking the "all statuses" default view.
    expect(new URL(url as string).searchParams.has("status")).toBe(false);
  });

  test("sends `status=failed` when caller asks for failures only", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useWebhookDeliveriesAdmin({ status: "failed" }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("status")).toBe("failed");
  });

  test("sends `status=delivered` for the success-only view", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useWebhookDeliveriesAdmin({ status: "delivered" }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("status")).toBe("delivered");
  });
});


// ---------- Other filters ----------


describe("useWebhookDeliveriesAdmin / event_type + org + subscription pass-through", () => {
  test("forwards every filter as a distinct query param", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const orgId = "11111111-1111-1111-1111-111111111111";
    const subId = "22222222-2222-2222-2222-222222222222";

    const { result } = renderHook(
      () =>
        useWebhookDeliveriesAdmin({
          event_type: "rfq.created",
          organization_id: orgId,
          subscription_id: subId,
          limit: 25,
        }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    const params = new URL(url as string).searchParams;
    expect(params.get("event_type")).toBe("rfq.created");
    expect(params.get("organization_id")).toBe(orgId);
    expect(params.get("subscription_id")).toBe(subId);
    expect(params.get("limit")).toBe("25");
  });

  test("default limit is 50", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useWebhookDeliveriesAdmin(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).searchParams.get("limit")).toBe("50");
  });
});


// ---------- Query-key shape ----------


describe("webhookDeliveriesAdminKeys / namespacing", () => {
  test("all keys live under [admin, webhook-deliveries]", () => {
    const list = webhookDeliveriesAdminKeys.list();
    const summary = webhookDeliveriesAdminKeys.summary();

    expect(list.slice(0, 2)).toEqual(["admin", "webhook-deliveries"]);
    expect(summary.slice(0, 2)).toEqual(["admin", "webhook-deliveries"]);
  });

  test("does NOT collide with slack-deliveries keys", () => {
    // Both surfaces live under `["admin"]` so a top-level invalidate
    // wipes both, but the second segment MUST differ so a targeted
    // invalidate of one doesn't trash the other.
    const list = webhookDeliveriesAdminKeys.list();
    expect(list[1]).toBe("webhook-deliveries");
    expect(list[1]).not.toBe("slack-deliveries");
  });

  test("list and summary are separately addressable", () => {
    const list = webhookDeliveriesAdminKeys.list();
    const summary = webhookDeliveriesAdminKeys.summary();
    expect(list[2]).toBe("list");
    expect(summary[2]).toBe("summary");
  });

  test("list keys vary on each filter so cached entries don't collide", () => {
    const all = webhookDeliveriesAdminKeys.list();
    const onlyEventType = webhookDeliveriesAdminKeys.list("rfq.created");
    const onlyStatus = webhookDeliveriesAdminKeys.list(undefined, "failed");
    const onlyOrg = webhookDeliveriesAdminKeys.list(
      undefined,
      undefined,
      "11111111-1111-1111-1111-111111111111",
    );
    const onlySub = webhookDeliveriesAdminKeys.list(
      undefined,
      undefined,
      undefined,
      "22222222-2222-2222-2222-222222222222",
    );

    const fingerprints = new Set(
      [all, onlyEventType, onlyStatus, onlyOrg, onlySub].map((k) =>
        JSON.stringify(k),
      ),
    );
    expect(fingerprints.size).toBe(5);
  });
});


// ---------- Envelope unwrapping ----------


describe("useWebhookDeliveriesAdmin / envelope unwrapping", () => {
  test("returns the rows array from the envelope's `data` field", async () => {
    const rows = [
      {
        id: "00000000-0000-0000-0000-000000000001",
        organization_id: "00000000-0000-0000-0000-000000000002",
        subscription_id: "00000000-0000-0000-0000-000000000003",
        event_type: "rfq.created",
        status: "delivered",
        attempt_count: 1,
        response_status: 200,
        response_body_snippet: "OK",
        error_message: null,
        next_retry_at: null,
        delivered_at: "2026-05-05T12:00:00Z",
        created_at: "2026-05-05T12:00:00Z",
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rows));

    const { result } = renderHook(() => useWebhookDeliveriesAdmin(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(rows);
  });

  test("returns [] when envelope's `data` is null", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useWebhookDeliveriesAdmin(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([]);
  });
});


// ---------- Detail hook (drilldown) ----------


describe("useWebhookDeliveryAdminDetail / URL", () => {
  const TEST_ID = "00000000-0000-0000-0000-000000000001";

  test("GETs /api/v1/admin/webhook-deliveries/{id} with the supplied id", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        id: TEST_ID,
        organization_id: "00000000-0000-0000-0000-000000000002",
        subscription_id: "00000000-0000-0000-0000-000000000003",
        event_type: "rfq.created",
        status: "delivered",
        attempt_count: 1,
        response_status: 200,
        response_body_snippet: "OK",
        error_message: null,
        next_retry_at: null,
        delivered_at: "2026-05-05T12:00:00Z",
        created_at: "2026-05-05T12:00:00Z",
        payload: { rfq_id: "abc" },
      }),
    );

    const { result } = renderHook(
      () => useWebhookDeliveryAdminDetail(TEST_ID),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      `/api/v1/admin/webhook-deliveries/${TEST_ID}`,
    );
    expect((init as RequestInit).method ?? "GET").toBe("GET");
  });
});


describe("useWebhookDeliveryAdminDetail / disabled when id is undefined", () => {
  test("does NOT fire the request when deliveryId is undefined", async () => {
    fetchMock.mockResolvedValue(envelopeResponse({}));

    renderHook(() => useWebhookDeliveryAdminDetail(undefined), {
      wrapper: makeWrapper(),
    });

    // Wait a tick for any potential queued query to fire.
    await new Promise((resolve) => setTimeout(resolve, 50));

    // The hook MUST be `enabled: Boolean(deliveryId)` — without that
    // guard, route landings without a resolved param (the brief
    // moment before `useParams()` populates) would 404 the API.
    expect(fetchMock).not.toHaveBeenCalled();
  });
});


describe("useWebhookDeliveryAdminDetail / cache-key shape", () => {
  test("cache key includes the delivery id (so different ids don't collide)", async () => {
    const idA = "00000000-0000-0000-0000-00000000000a";
    const idB = "00000000-0000-0000-0000-00000000000b";

    fetchMock.mockResolvedValue(
      envelopeResponse({
        id: idA,
        organization_id: "x",
        subscription_id: "y",
        event_type: "rfq.created",
        status: "delivered",
        attempt_count: 1,
        response_status: 200,
        response_body_snippet: null,
        error_message: null,
        next_retry_at: null,
        delivered_at: null,
        created_at: "2026-05-05T12:00:00Z",
        payload: {},
      }),
    );

    // Render two hooks with different ids inside the SAME wrapper
    // (shared QueryClient). If they shared a cache key, the second
    // hook would replay the first's cached data instead of fetching.
    const wrapper = makeWrapper();
    renderHook(() => useWebhookDeliveryAdminDetail(idA), { wrapper });
    renderHook(() => useWebhookDeliveryAdminDetail(idB), { wrapper });

    // Both renders should have triggered a fetch — distinct cache keys.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const calledUrls = fetchMock.mock.calls.map((c) =>
      new URL(c[0] as string).pathname,
    );
    expect(calledUrls).toContain(`/api/v1/admin/webhook-deliveries/${idA}`);
    expect(calledUrls).toContain(`/api/v1/admin/webhook-deliveries/${idB}`);
  });
});
