import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ApiError, apiRequest, apiRequestWithMeta } from "../api-client";

/**
 * Contract tests for `lib/api-client.ts` — the alternative fetch wrapper
 * used by SiteEye / mobile pages. Different signature from `apiFetch`:
 *
 *   apiRequest<T>(...)         → unwrapped data (T)
 *   apiRequestWithMeta<T>(...) → { data: T, meta }
 *
 * Locking in:
 *   1. `params` (NOT `query` — different key from api.ts) → search params,
 *      with same null/undefined drop semantics.
 *   2. `orgId` is OPTIONAL here (api.ts requires it). Only sets the
 *      X-Org-ID header when caller provides it. Mobile public-portal
 *      pages need this — they don't have an org context.
 *   3. `apiRequest` returns `env.data`; `apiRequestWithMeta` returns
 *      `{ data, meta }` with meta defaulting to `{}` on null.
 *   4. Error path mirrors `api.ts::ApiError` shape.
 */

const TOKEN = "test-token";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("api-client / params (not query)", () => {
  test("params populate search-string the same way `query` does in api.ts", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], meta: {} }));

    await apiRequest("/api/v1/things", {
      token: TOKEN,
      params: { limit: 50, offset: 0, q: "concrete" },
    });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("q")).toBe("concrete");
  });

  test("null / undefined params are dropped", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [] }));

    await apiRequest("/api/v1/things", {
      token: TOKEN,
      params: { kept: "yes", droppedNull: null, droppedUndef: undefined },
    });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("kept")).toBe("yes");
    expect(url.searchParams.has("droppedNull")).toBe(false);
    expect(url.searchParams.has("droppedUndef")).toBe(false);
  });
});

describe("api-client / headers", () => {
  test("X-Org-ID is omitted when orgId is not provided (mobile public portal)", async () => {
    // The public RFQ supplier portal calls api-client without an orgId
    // because the supplier isn't logged into any org. The wrapper must
    // not set X-Org-ID at all (not "X-Org-ID: undefined") — the API
    // routes accept that as "anonymous".
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiRequest("/api/v1/public/rfq/abc", { token: TOKEN });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Org-ID"]).toBeUndefined();
    expect(headers["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  test("X-Org-ID present when orgId is provided", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiRequest("/x", { token: TOKEN, orgId: "org-1" });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Org-ID"]).toBe("org-1");
  });

  test("default method is GET", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiRequest("/x", { token: TOKEN });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("GET");
  });

  test("AbortSignal threads through to fetch", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));
    const controller = new AbortController();

    await apiRequest("/x", { token: TOKEN, signal: controller.signal });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
  });
});

describe("api-client / unwrapping", () => {
  test("apiRequest returns the unwrapped `data` payload", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: { id: "abc", name: "Item" },
        meta: { total: 1 },
      }),
    );

    const result = await apiRequest<{ id: string; name: string }>("/x", {
      token: TOKEN,
    });

    expect(result).toEqual({ id: "abc", name: "Item" });
  });

  test("apiRequestWithMeta returns { data, meta }", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: [{ id: "v1" }],
        meta: { page: 1, per_page: 50, total: 1 },
      }),
    );

    const result = await apiRequestWithMeta<{ id: string }[]>("/x", {
      token: TOKEN,
    });

    expect(result.data).toEqual([{ id: "v1" }]);
    expect(result.meta).toEqual({ page: 1, per_page: 50, total: 1 });
  });

  test("apiRequestWithMeta defaults meta to {} when the envelope is missing it", async () => {
    // Envelope shape from older API endpoints sometimes omits `meta`. The
    // wrapper must default to `{}` so callers can `result.meta.total ?? 0`
    // without optional-chain hell.
    fetchMock.mockResolvedValue(jsonResponse({ data: [] }));

    const result = await apiRequestWithMeta<unknown[]>("/x", {
      token: TOKEN,
    });

    expect(result.meta).toEqual({});
  });
});

describe("api-client / error handling", () => {
  test("non-2xx → ApiError with all four fields", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          errors: [
            { code: "forbidden", message: "RLS denied", field: null },
          ],
        }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );

    try {
      await apiRequest("/x", { token: TOKEN });
      expect.fail("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(403);
      expect((err as ApiError).code).toBe("forbidden");
      expect((err as ApiError).message).toBe("RLS denied");
    }
  });

  test("non-2xx with empty body → falls back to res.statusText", async () => {
    fetchMock.mockResolvedValue(
      new Response("", { status: 504, statusText: "Gateway Timeout" }),
    );

    await expect(apiRequest("/x", { token: TOKEN })).rejects.toMatchObject({
      status: 504,
      code: "504",
      message: "Gateway Timeout",
    });
  });
});
