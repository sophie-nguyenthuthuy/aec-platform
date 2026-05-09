import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useGenerateRFI } from "@/hooks/drawbridge/useRFIs";

import { envelopeResponse, makeWrapper } from "./_harness";

/**
 * useGenerateRFI is the "AI-suggest an RFI from a conflict" path. The
 * hook applies one default — `priority: "high"` — that the conflicts
 * detail page relies on (open conflicts get a high-priority RFI by
 * default; the user can downgrade in the form below). Pin the default.
 */

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useGenerateRFI / contract", () => {
  test("POSTs conflict_id to /rfis/generate with priority=high default", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        id: "rfi-new",
        organization_id: "org",
        project_id: "p",
        number: "RFI-005",
        subject: "...",
        description: null,
        status: "open",
        priority: "high",
        related_document_ids: [],
        raised_by: null,
        assigned_to: null,
        due_date: null,
        response: null,
        created_at: "2026-05-01T00:00:00Z",
      }),
    );

    const { result } = renderHook(() => useGenerateRFI(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ conflict_id: "conflict-123" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/drawbridge/rfis/generate",
    );
    expect((init as RequestInit).method).toBe("POST");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      conflict_id: "conflict-123",
      priority: "high",
    });
  });

  test("explicit priority overrides the default", async () => {
    // Caller wants `priority: "normal"` for a low-severity conflict.
    // The hook's spread order (`{ priority: "high", ...payload }`) means
    // the caller wins. Pin it — a regression that flipped the spread
    // order would silently force every generated RFI to high priority.
    fetchMock.mockResolvedValue(
      envelopeResponse({
        id: "rfi-new",
        organization_id: "org",
        project_id: "p",
        number: "RFI-006",
        subject: "...",
        description: null,
        status: "open",
        priority: "normal",
        related_document_ids: [],
        raised_by: null,
        assigned_to: null,
        due_date: null,
        response: null,
        created_at: "2026-05-01T00:00:00Z",
      }),
    );

    const { result } = renderHook(() => useGenerateRFI(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      conflict_id: "c-1",
      priority: "normal",
      assigned_to: "user-1",
      due_date: "2026-06-01",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body).toEqual({
      conflict_id: "c-1",
      priority: "normal",
      assigned_to: "user-1",
      due_date: "2026-06-01",
    });
  });
});
