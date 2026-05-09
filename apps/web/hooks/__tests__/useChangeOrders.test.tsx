import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useChangeOrders } from "@/hooks/pulse/useChangeOrders";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useChangeOrders / contract", () => {
  test("GETs /pulse/change-orders (note hyphen, not underscore)", async () => {
    // Pin the hyphen — the type module + queryKey + python router all
    // use `change_orders` / `changeOrders` internally, but the URL is
    // hyphenated to match REST conventions. A regression that flipped
    // to `/change_orders` would 404 silently.
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useChangeOrders(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/pulse/change-orders");
  });

  test("filter params (project_id, status, limit, offset) feed through", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () =>
        useChangeOrders({
          project_id: "proj-1",
          status: "submitted",
          limit: 10,
          offset: 20,
        }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("project_id")).toBe("proj-1");
    expect(url.searchParams.get("status")).toBe("submitted");
    expect(url.searchParams.get("limit")).toBe("10");
    expect(url.searchParams.get("offset")).toBe("20");
  });

  test("undefined filters are omitted (not sent as 'undefined')", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useChangeOrders({ project_id: "p", status: undefined }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.has("project_id")).toBe(true);
    expect(url.searchParams.has("status")).toBe(false);
  });

  test("auth headers (token + orgId) are forwarded", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useChangeOrders(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer test-token");
    expect(headers.get("X-Org-Id")).toBe("00000000-0000-0000-0000-000000000000");
  });

  test("data is unwrapped from envelope; null data falls back to []", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ data: null, meta: null, errors: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useChangeOrders(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([]);
  });
});
