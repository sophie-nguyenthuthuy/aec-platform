import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useCodeguardScan } from "@/hooks/codeguard/useScan";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useCodeguardScan / contract", () => {
  test("POSTs project_id + parameters as JSON body to /codeguard/scan", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        check_id: "check-1",
        findings: [],
        regulations: [],
      }),
    );

    const { result } = renderHook(() => useCodeguardScan(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "proj-1",
      parameters: {
        project_type: "high_rise",
        total_area_m2: 12_000,
        floors_above: 25,
        max_height_m: 90,
      },
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe("/api/v1/codeguard/scan");
    expect((init as RequestInit).method).toBe("POST");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      project_id: "proj-1",
      parameters: {
        project_type: "high_rise",
        total_area_m2: 12_000,
        floors_above: 25,
        max_height_m: 90,
      },
    });
  });

  test("optional `categories` filter passes through verbatim", async () => {
    // The scan route supports filtering by regulation category; the page
    // uses it for "fire safety only" / "structural only" buttons. Pin
    // the passthrough so a refactor doesn't drop the field.
    fetchMock.mockResolvedValue(
      envelopeResponse({ check_id: "c-1", findings: [], regulations: [] }),
    );

    const { result } = renderHook(() => useCodeguardScan(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "p",
      parameters: { project_type: "office" },
      categories: ["fire_safety", "structure"],
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body.categories).toEqual(["fire_safety", "structure"]);
  });

  test("returns the unwrapped ScanResponse on success", async () => {
    const payload = {
      check_id: "c-1",
      findings: [
        {
          regulation_code: "QCVN 06:2022/BXD",
          section: "3.2.1",
          status: "non_compliant",
          severity: "high",
          excerpt: "Hành lang ≥ 1.4m",
        },
      ],
      regulations: [],
    };
    fetchMock.mockResolvedValue(envelopeResponse(payload));

    const { result } = renderHook(() => useCodeguardScan(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "p",
      parameters: { project_type: "office" },
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(payload);
  });
});
