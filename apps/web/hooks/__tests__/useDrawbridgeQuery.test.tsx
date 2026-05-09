import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useDrawbridgeQuery } from "@/hooks/drawbridge/useDrawbridgeQuery";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useDrawbridgeQuery / contract", () => {
  test("POSTs project_id + question as JSON body", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        answer: "Slab thickness is 200mm.",
        confidence: 0.85,
        source_documents: [],
        related_questions: [],
      }),
    );

    const { result } = renderHook(() => useDrawbridgeQuery(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "proj-1",
      question: "What is the slab thickness?",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe("/api/v1/drawbridge/query");
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      project_id: "proj-1",
      question: "What is the slab thickness?",
    });
  });

  test("optional filters (disciplines, document_ids, top_k, language) pass through verbatim", async () => {
    // The schema allows these but the hook doesn't transform them — pin
    // the passthrough so a future "smart default" doesn't silently
    // mutate caller intent. Especially `language` — defaults to vi
    // server-side, but if a caller wants en they expect it to honour.
    fetchMock.mockResolvedValue(
      envelopeResponse({
        answer: "ok",
        confidence: 1,
        source_documents: [],
        related_questions: [],
      }),
    );

    const { result } = renderHook(() => useDrawbridgeQuery(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "proj-1",
      question: "Why?",
      disciplines: ["structural", "mep"],
      document_ids: ["d1", "d2"],
      top_k: 10,
      language: "en",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    expect(body).toMatchObject({
      project_id: "proj-1",
      question: "Why?",
      disciplines: ["structural", "mep"],
      document_ids: ["d1", "d2"],
      top_k: 10,
      language: "en",
    });
  });

  test("returns the unwrapped QueryResponse data on success", async () => {
    // The hook's `return res.data` shape — components destructure
    // `.answer` / `.source_documents` directly off the mutation result.
    // A regression that returned the whole envelope would silently
    // surface as `undefined.answer` → blank UI.
    const payload = {
      answer: "Hành lang ≥ 1.4m theo QCVN.",
      confidence: 0.9,
      source_documents: [
        {
          document_id: "d-1",
          drawing_number: "A-101",
          title: "Floor 1",
          discipline: "architectural",
          page: 2,
          excerpt: "...",
          bbox: null,
        },
      ],
      related_questions: ["Cầu thang?"],
    };
    fetchMock.mockResolvedValue(envelopeResponse(payload));

    const { result } = renderHook(() => useDrawbridgeQuery(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ project_id: "p", question: "q" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(payload);
  });
});
