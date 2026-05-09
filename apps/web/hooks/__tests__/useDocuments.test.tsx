import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useDocuments } from "@/hooks/drawbridge/useDocuments";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useDocuments / contract", () => {
  test("GETs /documents with all filter params on the URL", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () =>
        useDocuments({
          project_id: "proj-1",
          discipline: "structural",
          doc_type: "drawing",
          processing_status: "ready",
          q: "column",
          limit: 100,
          offset: 25,
        }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/drawbridge/documents");
    expect(url.searchParams.get("project_id")).toBe("proj-1");
    expect(url.searchParams.get("discipline")).toBe("structural");
    expect(url.searchParams.get("doc_type")).toBe("drawing");
    expect(url.searchParams.get("processing_status")).toBe("ready");
    expect(url.searchParams.get("q")).toBe("column");
    expect(url.searchParams.get("limit")).toBe("100");
    expect(url.searchParams.get("offset")).toBe("25");
  });

  test("limit defaults to 50, offset to 0", async () => {
    // Pin the page-size default — the documents page renders 50/page.
    // A regression that flipped to 20 would silently halve the
    // first-page yield.
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useDocuments({}), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("offset")).toBe("0");
  });

  test("undefined filters are omitted, not sent as the literal string 'undefined'", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useDocuments({ project_id: "p" }), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.has("project_id")).toBe(true);
    // None of the optional fields appear at all.
    expect(url.searchParams.has("discipline")).toBe(false);
    expect(url.searchParams.has("doc_type")).toBe(false);
    expect(url.searchParams.has("q")).toBe(false);
  });

  test("returns { data, meta } shape (envelope unwrapped, not raw response)", async () => {
    const docs = [
      {
        id: "d-1",
        organization_id: "org",
        project_id: "p",
        document_set_id: null,
        file_id: null,
        doc_type: "drawing",
        drawing_number: "A-101",
        title: "Floor 1",
        revision: null,
        discipline: "architectural",
        scale: null,
        processing_status: "ready",
        extracted_data: {},
        thumbnail_url: null,
        created_at: "2026-04-15T00:00:00Z",
      },
    ];
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: docs,
          meta: { page: 1, per_page: 50, total: 47 },
          errors: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useDocuments({}), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.data).toEqual(docs);
    expect(result.current.data?.meta?.total).toBe(47);
  });
});
