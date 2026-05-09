import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useExtract } from "@/hooks/drawbridge/useExtract";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useExtract / contract", () => {
  test("POSTs document_id + target as JSON body", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        document_id: "doc-1",
        schedules: [],
        dimensions: [],
        materials: [],
        title_block: null,
      }),
    );

    const { result } = renderHook(() => useExtract(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      document_id: "doc-1",
      target: "dimensions",
      pages: [1, 2, 3],
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe("/api/v1/drawbridge/extract");
    expect((init as RequestInit).method).toBe("POST");
    // This hook posts JSON (unlike usePriceAlert which uses query) — verify
    // the body is the typed payload, not URL params.
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      target: "dimensions",
      document_id: "doc-1",
      pages: [1, 2, 3],
    });
  });

  test("target defaults to 'schedule' when caller omits it", async () => {
    // Default surfaces in the apps/web/app/(dashboard)/drawbridge/extract
    // page — a regression here would silently change which extractor
    // pipeline runs. The merge-order in the hook is `{ target: "schedule",
    // ...payload }`, so a caller passing `target: "all"` should win.
    fetchMock.mockResolvedValue(
      envelopeResponse({ document_id: "d", schedules: [], dimensions: [], materials: [], title_block: null }),
    );

    const { result } = renderHook(() => useExtract(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ document_id: "d" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body.target).toBe("schedule");
  });

  test("explicit target overrides the default", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({ document_id: "d", schedules: [], dimensions: [], materials: [], title_block: null }),
    );

    const { result } = renderHook(() => useExtract(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ document_id: "d", target: "all" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body.target).toBe("all");
  });

  test("non-2xx → mutation enters isError with the ApiError shape", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          errors: [{ code: "extraction_failed", message: "model timed out", field: null }],
        }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useExtract(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ document_id: "doc-1" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain("model timed out");
  });
});
