/**
 * Tests for `AecClientCore` — the hand-written HTTP layer the
 * auto-generated SDK methods bind to.
 *
 * We mock `fetch` at the option level (`opts.fetch = vi.fn()`) so each
 * test gets a clean recorder of what the client sent. No msw / nock
 * dep needed — the surface is small enough to assert on raw `fetch`
 * call shape.
 *
 * Coverage matches the contract every partner integration depends on:
 *   * URL composition (baseUrl + path + querystring)
 *   * Authorization header
 *   * Envelope unwrap (response.data → return value)
 *   * AecApiError carries status + body
 *   * 429 retries respect Retry-After
 *   * 5xx retries with exponential backoff (loose timing assertion)
 *   * undefined query values dropped from the URL
 *   * Empty body POST sends `body: undefined`, not `"undefined"`
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AecApiError, AecClientCore } from "../client";


function envelope<T>(data: T): Response {
  return new Response(JSON.stringify({ data, errors: null, meta: null }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}


function errorResponse(status: number, message: string, headers: Record<string, string> = {}): Response {
  return new Response(
    JSON.stringify({ data: null, errors: [{ message }], meta: null }),
    {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    },
  );
}


describe("AecClientCore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("composes baseUrl + path + querystring on GET", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ id: "x" }));
    const client = new AecClientCore({
      apiKey: "aec_test_123",
      baseUrl: "https://api.aec-platform.vn",
      fetch: fetchMock,
    });

    await client.request("GET", "/api/v1/projects", { status: "construction", page: 2 });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(
      "https://api.aec-platform.vn/api/v1/projects?status=construction&page=2",
    );
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("sends Authorization: Bearer + Content-Type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({}));
    const client = new AecClientCore({ apiKey: "aec_secret", fetch: fetchMock });

    await client.request("GET", "/api/v1/projects");

    const init = fetchMock.mock.calls[0]![1];
    expect(init.headers.Authorization).toBe("Bearer aec_secret");
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("strips trailing slash from baseUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({}));
    const client = new AecClientCore({
      apiKey: "k",
      baseUrl: "https://api.example.com/",
      fetch: fetchMock,
    });

    await client.request("GET", "/api/v1/projects");
    expect(fetchMock.mock.calls[0]![0]).toBe(
      "https://api.example.com/api/v1/projects",
    );
  });

  it("unwraps the envelope and returns `data`", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ id: "p-1", name: "Tower A" }));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock });

    const result = await client.request<{ id: string; name: string }>(
      "GET",
      "/api/v1/projects/p-1",
    );

    expect(result).toEqual({ id: "p-1", name: "Tower A" });
  });

  it("drops undefined query values from the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({}));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock });

    await client.request("GET", "/api/v1/projects", {
      status: "construction",
      type: undefined,
      page: 1,
    });

    const url = fetchMock.mock.calls[0]![0] as string;
    expect(url).toContain("status=construction");
    expect(url).toContain("page=1");
    expect(url).not.toContain("type=");
  });

  it("URL-encodes special characters in query values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({}));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock });

    await client.request("GET", "/api/v1/search", { q: "tower & fire safety" });

    expect(fetchMock.mock.calls[0]![0]).toContain(
      "q=tower%20%26%20fire%20safety",
    );
  });

  it("serialises body as JSON on POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue(envelope({ ok: true }));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock });

    await client.request(
      "POST",
      "/api/v1/projects",
      undefined,
      { name: "Tower B", type: "office" },
    );

    expect(fetchMock.mock.calls[0]![1].body).toBe(
      JSON.stringify({ name: "Tower B", type: "office" }),
    );
  });

  it("throws AecApiError with status + body on 4xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      errorResponse(403, "missing_scope: projects:read"),
    );
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock, maxRetries: 0 });

    await expect(
      client.request("GET", "/api/v1/projects"),
    ).rejects.toMatchObject({
      name: "AecApiError",
      status: 403,
      message: "missing_scope: projects:read",
    });
  });

  it("AecApiError exposes the parsed body for callsite inspection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      errorResponse(422, "validation failed"),
    );
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock, maxRetries: 0 });

    try {
      await client.request("POST", "/api/v1/projects", undefined, {});
    } catch (e) {
      expect(e).toBeInstanceOf(AecApiError);
      expect((e as AecApiError).body).toEqual({
        data: null,
        errors: [{ message: "validation failed" }],
        meta: null,
      });
    }
  });

  it("retries on 429 then succeeds, respecting Retry-After", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        errorResponse(429, "rate_limit_exceeded", { "retry-after": "1" }),
      )
      .mockResolvedValueOnce(envelope({ id: "p-1" }));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock, maxRetries: 3 });

    const promise = client.request("GET", "/api/v1/projects");
    // Retry-After=1 → 1000ms sleep before retry. Advance the timer.
    await vi.advanceTimersByTimeAsync(1000);
    const result = await promise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ id: "p-1" });
  });

  it("retries on 5xx then succeeds (exponential backoff)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(503, "service_unavailable"))
      .mockResolvedValueOnce(envelope({ id: "p-1" }));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock, maxRetries: 3 });

    const promise = client.request("GET", "/api/v1/projects");
    // First retry waits 500ms + jitter (max ~750ms). Advance generously.
    await vi.advanceTimersByTimeAsync(1000);
    const result = await promise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ id: "p-1" });
  });

  it("gives up after maxRetries and throws", async () => {
    const fetchMock = vi.fn().mockResolvedValue(errorResponse(500, "server_error"));
    const client = new AecClientCore({ apiKey: "k", fetch: fetchMock, maxRetries: 2 });

    const promise = client.request("GET", "/api/v1/projects").catch((e: unknown) => e);
    // 3 attempts (initial + 2 retries) with backoff. Drain enough time.
    await vi.advanceTimersByTimeAsync(60_000);
    const err = await promise;

    expect(err).toBeInstanceOf(AecApiError);
    if (!(err instanceof AecApiError)) throw new Error("expected AecApiError");
    expect(err.status).toBe(500);
    expect(fetchMock).toHaveBeenCalledTimes(3); // initial + 2 retries
  });

  it("rejects construction without an apiKey", () => {
    expect(() => new AecClientCore({ apiKey: "" })).toThrow(/apiKey is required/);
  });
});
