import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ApiError, apiFetch } from "../api";

/**
 * Contract tests for `lib/api.ts::apiFetch` — the load-bearing fetch
 * wrapper every TanStack hook in `apps/web/hooks/` calls.
 *
 * What we lock in
 * ---------------
 *   1. URL construction: relative path joins onto BASE_URL; absolute path
 *      passes through; `query` becomes `URLSearchParams`; `null` /
 *      `undefined` query values are omitted (not stringified).
 *   2. Headers: `Authorization: Bearer <token>` + `X-Org-ID` always set.
 *      Caller-supplied headers merge with (and can override) the defaults.
 *   3. Body: `JSON.stringify(body)` when present; `undefined` body becomes
 *      no body at all (so `Content-Length: 0` not `Content-Length: 9`).
 *   4. Error envelope unwrap: non-2xx → `ApiError` with `status`, `code`,
 *      `message`, `field` pulled from the first entry of `errors[]`.
 *      Falls back to `res.statusText` when the body is empty / non-JSON.
 *
 * Why this matters: when I wrote the costpulse-prices Playwright spec
 * earlier, I incorrectly assumed `usePriceAlert` sent JSON body — it
 * actually sends URL-encoded params. A unit test asserting
 * "POST + query only → search params, no body" would have caught the
 * wrong assertion at unit-test speed instead of ten-second Playwright
 * runs in jsdom.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
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

describe("apiFetch / URL construction", () => {
  test("relative path is joined onto NEXT_PUBLIC_API_URL (or localhost:8000 fallback)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/api/v1/users", { token: TOKEN, orgId: ORG_ID });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0]![0] as string;
    // BASE_URL falls back to "http://localhost:8000" when
    // NEXT_PUBLIC_API_URL is unset (the case under Vitest).
    expect(url).toBe("http://localhost:8000/api/v1/users");
  });

  test("absolute path passes through untouched", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("https://api.example.com/v2/things", {
      token: TOKEN,
      orgId: ORG_ID,
    });

    expect(fetchMock.mock.calls[0]![0]).toBe(
      "https://api.example.com/v2/things",
    );
  });

  test("query values become search params", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/api/v1/things", {
      token: TOKEN,
      orgId: ORG_ID,
      query: { limit: 50, offset: 0, q: "concrete", active: true },
    });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("offset")).toBe("0");
    expect(url.searchParams.get("q")).toBe("concrete");
    expect(url.searchParams.get("active")).toBe("true");
  });

  test("null and undefined query values are dropped, not stringified", async () => {
    // Regression target: previous versions of this helper turned
    // `province: null` into `province=null` (literal string), which the
    // API treated as "filter by the string null" rather than "no filter".
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/api/v1/things", {
      token: TOKEN,
      orgId: ORG_ID,
      query: { kept: "yes", droppedNull: null, droppedUndef: undefined },
    });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("kept")).toBe("yes");
    expect(url.searchParams.has("droppedNull")).toBe(false);
    expect(url.searchParams.has("droppedUndef")).toBe(false);
  });
});

describe("apiFetch / headers", () => {
  test("auth + org headers always present", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/x", { token: "abc", orgId: "org-1" });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer abc");
    expect(headers["X-Org-ID"]).toBe("org-1");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  test("caller-supplied headers merge with defaults", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/x", {
      token: TOKEN,
      orgId: ORG_ID,
      headers: { "X-Trace-Id": "trace-123" },
    });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Trace-Id"]).toBe("trace-123");
    expect(headers["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  test("caller-supplied header can override a default", async () => {
    // Deliberate: the spread order means caller wins. Documented behaviour
    // — some routes accept multipart/form-data and need to override CT.
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/x", {
      token: TOKEN,
      orgId: ORG_ID,
      headers: { "Content-Type": "multipart/form-data; boundary=xxx" },
    });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe(
      "multipart/form-data; boundary=xxx",
    );
  });
});

describe("apiFetch / body", () => {
  test("body present → JSON.stringify(body)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/x", {
      method: "POST",
      token: TOKEN,
      orgId: ORG_ID,
      body: { name: "Concrete C30", price_vnd: 2_000_000 },
    });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.body).toBe(
      JSON.stringify({ name: "Concrete C30", price_vnd: 2_000_000 }),
    );
  });

  test("undefined body → no body sent", async () => {
    // Critical for `query`-only POSTs (e.g. `usePriceAlert`). When body is
    // omitted, the request must not stringify `undefined` → "undefined" or
    // send "null" — both would confuse the API. fetch's `body: undefined`
    // is the correct shape for "no body".
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/x", {
      method: "POST",
      token: TOKEN,
      orgId: ORG_ID,
      query: { material_code: "CONC_C30" },
    });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.body).toBeUndefined();
  });

  test("body=null is JSON.stringify-ed to the literal string 'null'", async () => {
    // Document existing behaviour: `body: null` is treated as a real
    // value to send, not as "no body". If a caller wants no body, omit
    // the key entirely. This test pins the behaviour so a refactor
    // doesn't silently change it.
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));

    await apiFetch("/x", {
      method: "POST",
      token: TOKEN,
      orgId: ORG_ID,
      body: null,
    });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.body).toBe("null");
  });
});

describe("apiFetch / error handling", () => {
  test("envelope shape — successful response is returned as-is", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: { id: 1, name: "ok" },
        meta: { total: 1 },
        errors: null,
      }),
    );

    const env = await apiFetch<{ id: number; name: string }>("/x", {
      token: TOKEN,
      orgId: ORG_ID,
    });

    expect(env.data).toEqual({ id: 1, name: "ok" });
    expect(env.meta).toEqual({ total: 1 });
  });

  test("non-2xx with structured error → ApiError with all four fields", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          errors: [
            {
              code: "validation_error",
              message: "area_sqm must be > 0",
              field: "area_sqm",
            },
          ],
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(
      apiFetch("/x", { token: TOKEN, orgId: ORG_ID }),
    ).rejects.toMatchObject({
      // Use a structural match, not `.toBeInstanceOf(ApiError)`, because
      // toMatchObject sees the prototype too.
      status: 422,
      code: "validation_error",
      message: "area_sqm must be > 0",
      field: "area_sqm",
    });
  });

  test("non-2xx with details_url → ApiError carries detailsUrl", async () => {
    // Mirrors the codeguard cap-check 429 envelope shape. The frontend
    // toast/inline-error renderers read `detailsUrl` to decide whether
    // to show a "Xem hạn mức" CTA — pin both the carry-through AND the
    // snake_case → camelCase rename here, since a regression on either
    // would silently drop the CTA.
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          errors: [
            {
              code: "429",
              message: "Monthly input-token quota exceeded",
              field: null,
              details_url: "/codeguard/quota",
            },
          ],
        }),
        { status: 429, headers: { "Content-Type": "application/json" } },
      ),
    );

    try {
      await apiFetch("/x", { token: TOKEN, orgId: ORG_ID });
      expect.fail("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(429);
      expect((err as ApiError).detailsUrl).toBe("/codeguard/quota");
    }
  });

  test("non-2xx without details_url → detailsUrl is undefined", async () => {
    // Existing 4xx/5xx callers don't populate `details_url`; the
    // ApiError should carry undefined rather than null. Pin the
    // distinction so a future refactor that coerces "no URL" → null
    // doesn't silently start rendering empty-href CTAs.
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          errors: [{ code: "400", message: "bad input", field: null }],
        }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );

    try {
      await apiFetch("/x", { token: TOKEN, orgId: ORG_ID });
      expect.fail("expected throw");
    } catch (err) {
      expect((err as ApiError).detailsUrl).toBeUndefined();
    }
  });

  test("non-2xx with empty body → ApiError falls back to res.statusText", async () => {
    fetchMock.mockResolvedValue(
      new Response("", { status: 502, statusText: "Bad Gateway" }),
    );

    try {
      await apiFetch("/x", { token: TOKEN, orgId: ORG_ID });
      expect.fail("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(502);
      expect((err as ApiError).code).toBe("502");
      expect((err as ApiError).message).toBe("Bad Gateway");
    }
  });

  test("non-2xx with non-JSON body → still ApiError, message uses statusText", async () => {
    // Some upstream proxies (CloudFront, ALB) return HTML for 5xx. The
    // `res.json().catch(() => ({}))` swallow keeps us from unhandled
    // rejection; the error fallback chain should still produce a usable
    // ApiError.
    fetchMock.mockResolvedValue(
      new Response("<html>500</html>", {
        status: 500,
        statusText: "Internal Server Error",
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(
      apiFetch("/x", { token: TOKEN, orgId: ORG_ID }),
    ).rejects.toMatchObject({
      status: 500,
      code: "500",
      message: "Internal Server Error",
    });
  });
});
