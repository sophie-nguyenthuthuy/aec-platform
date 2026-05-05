import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useEstimates } from "@/hooks/costpulse/useEstimates";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useEstimates / contract", () => {
  test("GETs /costpulse/estimates with page=1 / per_page=20 defaults", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useEstimates(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/costpulse/estimates");
    expect(url.searchParams.get("page")).toBe("1");
    expect(url.searchParams.get("per_page")).toBe("20");
  });

  test("project_id + status filters land on the URL when provided", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useEstimates({ project_id: "proj-1", status: "approved" }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("project_id")).toBe("proj-1");
    expect(url.searchParams.get("status")).toBe("approved");
  });

  test("undefined filters are dropped — `?? null` route through the API URL builder", async () => {
    // The hook spells `filters.project_id ?? null` — apiFetch's URL
    // builder then drops null values. Net effect: undefined filters
    // become absent params. Pin the pipeline so a refactor that
    // dropped the `?? null` (or replaced apiFetch's null-skip) still
    // ends up with absent params, not literal "null".
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useEstimates(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.has("project_id")).toBe(false);
    expect(url.searchParams.has("status")).toBe(false);
  });

  test("returns { items, meta } shape", async () => {
    const estimates = [
      {
        id: "est-1",
        organization_id: "org",
        project_id: "p",
        name: "Tower A v3",
        version: 3,
        status: "approved",
        total_vnd: 1_500_000_000,
        confidence: "detailed",
        method: "ai_generated",
        created_by: null,
        approved_by: null,
        created_at: "2026-04-15T08:00:00Z",
      },
    ];
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: estimates,
          meta: { page: 1, per_page: 20, total: 12 },
          errors: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useEstimates(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items).toEqual(estimates);
    expect(result.current.data?.meta?.total).toBe(12);
  });
});
