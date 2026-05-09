import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useAnswerRFI } from "@/hooks/drawbridge/useRFIs";

import { envelopeResponse, makeWrapper } from "./_harness";

/**
 * useAnswerRFI POSTs to `/rfis/{id}/answer` — id in the URL, response
 * text + close-on-answer flag in the body. The `close = true` default
 * is the contract: most users answer-and-close in one shot; only a
 * minority pre-flag a "draft answer" by passing `close: false`.
 */

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const RFI_ID = "rfi-abc";

const fakeRfi = (overrides: Record<string, unknown> = {}) => ({
  id: RFI_ID,
  organization_id: "org",
  project_id: "p",
  number: "RFI-001",
  subject: "Slab thickness?",
  description: null,
  status: "answered",
  priority: "high",
  related_document_ids: [],
  raised_by: null,
  assigned_to: null,
  due_date: null,
  response: "200mm per S-301",
  created_at: "2026-05-01T00:00:00Z",
  ...overrides,
});

describe("useAnswerRFI / contract", () => {
  test("POSTs to /rfis/{id}/answer with response + close=true default", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(fakeRfi()));

    const { result } = renderHook(() => useAnswerRFI(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      id: RFI_ID,
      response: "Slab thickness is 200mm per drawing S-301.",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    // id MUST be in the URL — the route key is `:id`. Putting it in
    // the body (a regression that "simplified" the URL) would 404.
    expect(new URL(url as string).pathname).toBe(
      `/api/v1/drawbridge/rfis/${RFI_ID}/answer`,
    );
    expect((init as RequestInit).method).toBe("POST");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      response: "Slab thickness is 200mm per drawing S-301.",
      close: true,
    });
  });

  test("close=false carries through (draft-answer flow)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(fakeRfi({ status: "open" })));

    const { result } = renderHook(() => useAnswerRFI(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      id: RFI_ID,
      response: "Working on it — needs structural confirmation.",
      close: false,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body.close).toBe(false);
  });

  test("returns the unwrapped Rfi on success", async () => {
    const updated = fakeRfi({ response: "Confirmed: 200mm." });
    fetchMock.mockResolvedValue(envelopeResponse(updated));

    const { result } = renderHook(() => useAnswerRFI(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ id: RFI_ID, response: "Confirmed: 200mm." });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(updated);
  });
});
