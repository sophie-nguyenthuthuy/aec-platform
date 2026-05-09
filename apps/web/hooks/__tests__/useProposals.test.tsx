import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useProposals } from "@/hooks/winwork/useProposals";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useProposals / contract", () => {
  test("GETs /proposals with page + per_page defaults", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useProposals(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/winwork/proposals");
    expect(url.searchParams.get("page")).toBe("1");
    expect(url.searchParams.get("per_page")).toBe("20");
  });

  test("status + q filters override defaults but don't replace pagination", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useProposals({ status: "won", q: "marina" }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("status")).toBe("won");
    expect(url.searchParams.get("q")).toBe("marina");
    // Defaults still applied (caller didn't override page/per_page).
    expect(url.searchParams.get("page")).toBe("1");
    expect(url.searchParams.get("per_page")).toBe("20");
  });

  test("returns { items, total } — total falls back to 0 when meta is missing", async () => {
    // The hook reads `res.meta?.total ?? 0`. A regression that left it
    // as `res.meta.total` (no nullish) would crash on any endpoint
    // that returns an envelope without meta — and our public-portal
    // endpoints do exactly that.
    fetchMock.mockResolvedValue(envelopeResponse([{ id: "p1" }, { id: "p2" }]));

    const { result } = renderHook(() => useProposals(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.total).toBe(0);
  });

  test("reads meta.total when the envelope provides it", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: [{ id: "p1" }],
          meta: { total: 137 },
          errors: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useProposals(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.total).toBe(137);
  });
});
