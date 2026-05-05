import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useTenders } from "@/hooks/bidradar/useTenders";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useTenders / contract", () => {
  test("GETs /bidradar/tenders with limit=20 / offset=0 defaults", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useTenders(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/bidradar/tenders");
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("offset")).toBe("0");
  });

  test("filter params (q, province, discipline) feed through to the URL", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () =>
        useTenders({
          q: "metro",
          province: "HCMC",
          discipline: "civil",
        }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("q")).toBe("metro");
    expect(url.searchParams.get("province")).toBe("HCMC");
    expect(url.searchParams.get("discipline")).toBe("civil");
  });

  test("returns { items, total } — total defaults to 0 when meta absent", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([{ id: "t1" }]));

    const { result } = renderHook(() => useTenders(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.total).toBe(0);
  });
});
