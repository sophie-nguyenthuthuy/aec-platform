import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { usePackages } from "@/hooks/handover/usePackages";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePackages / contract", () => {
  test("GETs /handover/packages with project_id + status + pagination", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () =>
        usePackages({
          project_id: "proj-1",
          status: "in_review",
          limit: 50,
          offset: 10,
        }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/handover/packages");
    expect(url.searchParams.get("project_id")).toBe("proj-1");
    expect(url.searchParams.get("status")).toBe("in_review");
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("offset")).toBe("10");
  });

  test("limit defaults to 20, offset to 0", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => usePackages(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("offset")).toBe("0");
  });

  test("returns { data, meta } shape (envelope unwrapped)", async () => {
    const pkgs = [
      {
        id: "pkg-1",
        organization_id: "org",
        project_id: "p",
        name: "Bàn giao giai đoạn 1",
        status: "draft",
        closeout_total: 12,
        closeout_done: 8,
        warranty_expiring: 1,
        open_defects: 2,
        created_at: "2026-04-15T08:00:00Z",
      },
    ];
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: pkgs,
          meta: { page: 1, per_page: 20, total: 5 },
          errors: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => usePackages(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.data).toEqual(pkgs);
    expect(result.current.data?.meta?.total).toBe(5);
  });
});
