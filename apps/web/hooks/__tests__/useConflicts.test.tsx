import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useUpdateConflict, useConflictScan } from "@/hooks/drawbridge/useConflicts";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useUpdateConflict / contract", () => {
  test("PATCHes /conflicts/{id} with status + resolution_notes in body", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        id: "c-1",
        status: "resolved",
        severity: "critical",
      }),
    );

    const { result } = renderHook(() => useUpdateConflict(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      id: "c-1",
      status: "resolved",
      resolution_notes: "Used the structural value (180mm).",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    // Path uses :id — NOT a query param. Server-side this routes to a
    // specific conflict; if the hook ever moved id into the body or
    // query string the route would 404.
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/drawbridge/conflicts/c-1",
    );
    expect((init as RequestInit).method).toBe("PATCH");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      status: "resolved",
      resolution_notes: "Used the structural value (180mm).",
    });
  });

  test("optional resolution_notes can be omitted (dismiss-without-comment flow)", async () => {
    // Conflicts dismissed without a note (the user just wanted them off
    // the dashboard) — the hook must not fabricate an empty string,
    // because the server-side schema treats "" different from `null`.
    // Verify undefined passes through as undefined to the body.
    fetchMock.mockResolvedValue(envelopeResponse({ id: "c-1", status: "dismissed" }));

    const { result } = renderHook(() => useUpdateConflict(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ id: "c-1", status: "dismissed" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body).toEqual({ status: "dismissed", resolution_notes: undefined });
  });
});

describe("useConflictScan / contract", () => {
  test("POSTs project_id + optional filters to /conflict-scan", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        project_id: "p-1",
        scanned_documents: 12,
        candidates_evaluated: 34,
        conflicts_found: 3,
        conflicts: [],
      }),
    );

    const { result } = renderHook(() => useConflictScan(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "p-1",
      document_ids: ["d1", "d2"],
      severities: ["critical", "major"],
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/drawbridge/conflict-scan",
    );
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      project_id: "p-1",
      document_ids: ["d1", "d2"],
      severities: ["critical", "major"],
    });
  });

  test("project_id alone is enough — no filters required", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        project_id: "p-1",
        scanned_documents: 0,
        candidates_evaluated: 0,
        conflicts_found: 0,
        conflicts: [],
      }),
    );

    const { result } = renderHook(() => useConflictScan(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ project_id: "p-1" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body).toEqual({ project_id: "p-1" });
  });
});
