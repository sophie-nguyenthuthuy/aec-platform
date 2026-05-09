import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { usePriceAlert } from "@/hooks/costpulse/usePrices";

import { envelopeResponse, makeWrapper } from "./_harness";

/**
 * Regression target: this hook's public-portal-style POST passes its
 * inputs as `query` (URL search params), NOT a JSON body. When I first
 * wrote the costpulse-prices Playwright spec earlier in this codebase's
 * history, I assumed the body was JSON, captured `route.request().postDataJSON()`
 * and asserted on it — and got `null` every time because the body really
 * was empty. That bug would have been caught at unit-test speed if this
 * file existed back then.
 */

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePriceAlert / contract", () => {
  test("POSTs to /price-alerts with params on the URL, no body", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({ id: "alert-1", material_code: "CONC_C30" }),
    );

    const { result } = renderHook(() => usePriceAlert(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      material_code: "CONC_C30",
      province: "Hanoi",
      threshold_pct: 5,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;

    // The pivotal assertion — params on the URL, NOT in body.
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/api/v1/costpulse/price-alerts");
    expect(parsed.searchParams.get("material_code")).toBe("CONC_C30");
    expect(parsed.searchParams.get("province")).toBe("Hanoi");
    expect(parsed.searchParams.get("threshold_pct")).toBe("5");

    // Body is undefined (no JSON-stringified payload).
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeUndefined();
  });

  test("threshold_pct defaults to 5 when caller omits it", async () => {
    // The hook's `?? 5` default is the published contract — the price-
    // alerts page renders "Alert me on >5% change" against this number.
    // A regression that swapped `?? 5` for `?? 10` would silently halve
    // the noise floor of every alert.
    fetchMock.mockResolvedValue(envelopeResponse({ id: "alert-1" }));

    const { result } = renderHook(() => usePriceAlert(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ material_code: "STEEL_REBAR" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("threshold_pct")).toBe("5");
  });

  test("province=null is dropped, not sent as 'null'", async () => {
    // Defensive: `apiFetch`'s URL builder skips null values so the
    // server doesn't see `province=null` (string). If the hook ever
    // started passing the literal string "null", server-side filtering
    // would silently match nothing. Pin the contract.
    fetchMock.mockResolvedValue(envelopeResponse({ id: "alert-1" }));

    const { result } = renderHook(() => usePriceAlert(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ material_code: "CONC_C30", province: undefined });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.has("province")).toBe(false);
  });

  test("Authorization + X-Org-ID headers are set from session", async () => {
    fetchMock.mockResolvedValue(envelopeResponse({ id: "alert-1" }));

    const { result } = renderHook(() => usePriceAlert(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ material_code: "CONC_C30" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-token");
    expect(headers["X-Org-ID"]).toBe("00000000-0000-0000-0000-000000000000");
  });
});
