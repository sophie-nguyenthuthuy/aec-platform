import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useUploadDocument } from "@/hooks/drawbridge/useDocuments";

import { makeWrapper } from "./_harness";

/**
 * useUploadDocument is the only Drawbridge hook that bypasses `apiFetch`
 * (which forces `Content-Type: application/json`) and goes straight to
 * `fetch` with a FormData body. The browser then sets a multipart
 * Content-Type with a boundary itself.
 *
 * What we lock in:
 *   1. POST to `/api/v1/drawbridge/documents/upload` with a `FormData`
 *      body (NOT JSON) — a regression that JSON-stringified the input
 *      would silently break the upload route's multipart parser.
 *   2. Required form fields (file + project_id) always present.
 *   3. Optional fields only attach when the caller provides them —
 *      passing undefined for `discipline` must NOT result in
 *      `discipline=undefined` (string) on the form.
 *   4. Authorization + X-Org-ID headers carry the session — no
 *      Content-Type header (the browser injects it with boundary).
 *   5. Non-2xx → throws an Error with the server's error message.
 */

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const fakeFile = (name = "plan.pdf", type = "application/pdf") =>
  new File(["%PDF-1.4 fake"], name, { type });

function jsonOk(data: unknown): Response {
  return new Response(JSON.stringify({ data }), {
    status: 201,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useUploadDocument / contract", () => {
  test("POSTs FormData to /documents/upload (not JSON)", async () => {
    fetchMock.mockResolvedValue(
      jsonOk({
        id: "doc-1",
        organization_id: "org-1",
        project_id: "proj-1",
        document_set_id: null,
        file_id: "file-1",
        doc_type: null,
        drawing_number: null,
        title: null,
        revision: null,
        discipline: null,
        scale: null,
        processing_status: "pending",
        extracted_data: {},
        thumbnail_url: null,
        created_at: "2026-05-01T00:00:00Z",
      }),
    );

    const { result } = renderHook(() => useUploadDocument(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      file: fakeFile(),
      project_id: "proj-1",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/drawbridge/documents/upload",
    );
    expect((init as RequestInit).method).toBe("POST");
    // The body MUST be FormData. JSON would mean a regression that
    // bypassed `new FormData()`.
    expect((init as RequestInit).body).toBeInstanceOf(FormData);

    const form = (init as RequestInit).body as FormData;
    expect(form.get("project_id")).toBe("proj-1");
    expect(form.get("file")).toBeInstanceOf(File);
    expect((form.get("file") as File).name).toBe("plan.pdf");
  });

  test("optional fields attach only when provided (not as 'undefined')", async () => {
    // Common bug shape: `form.append("discipline", input.discipline)` with
    // no presence check would stringify undefined → "undefined". The
    // server-side parser would then choke on it as an invalid enum.
    fetchMock.mockResolvedValue(
      jsonOk({
        id: "doc-2",
        organization_id: "org",
        project_id: "p",
        document_set_id: null,
        file_id: "f",
        doc_type: null,
        drawing_number: null,
        title: null,
        revision: null,
        discipline: null,
        scale: null,
        processing_status: "pending",
        extracted_data: {},
        thumbnail_url: null,
        created_at: "2026-05-01T00:00:00Z",
      }),
    );

    const { result } = renderHook(() => useUploadDocument(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile(), project_id: "p" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const form = (fetchMock.mock.calls[0]![1] as RequestInit).body as FormData;
    // The fields the caller didn't provide must not appear at all.
    expect(form.has("discipline")).toBe(false);
    expect(form.has("doc_type")).toBe(false);
    expect(form.has("drawing_number")).toBe(false);
    expect(form.has("title")).toBe(false);
  });

  test("all optional fields pass through when provided", async () => {
    fetchMock.mockResolvedValue(
      jsonOk({
        id: "doc-3",
        organization_id: "org",
        project_id: "p",
        document_set_id: "set-1",
        file_id: "f",
        doc_type: "drawing",
        drawing_number: "A-101",
        title: "Ground floor",
        revision: "B",
        discipline: "architectural",
        scale: "1:100",
        processing_status: "pending",
        extracted_data: {},
        thumbnail_url: null,
        created_at: "2026-05-01T00:00:00Z",
      }),
    );

    const { result } = renderHook(() => useUploadDocument(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      file: fakeFile(),
      project_id: "p",
      document_set_id: "set-1",
      doc_type: "drawing",
      drawing_number: "A-101",
      title: "Ground floor",
      revision: "B",
      discipline: "architectural",
      scale: "1:100",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const form = (fetchMock.mock.calls[0]![1] as RequestInit).body as FormData;
    expect(form.get("document_set_id")).toBe("set-1");
    expect(form.get("doc_type")).toBe("drawing");
    expect(form.get("drawing_number")).toBe("A-101");
    expect(form.get("title")).toBe("Ground floor");
    expect(form.get("revision")).toBe("B");
    expect(form.get("discipline")).toBe("architectural");
    expect(form.get("scale")).toBe("1:100");
  });

  test("Authorization + X-Org-ID headers set; no Content-Type (browser-set boundary)", async () => {
    fetchMock.mockResolvedValue(
      jsonOk({
        id: "doc-4",
        organization_id: "org",
        project_id: "p",
        document_set_id: null,
        file_id: "f",
        doc_type: null,
        drawing_number: null,
        title: null,
        revision: null,
        discipline: null,
        scale: null,
        processing_status: "pending",
        extracted_data: {},
        thumbnail_url: null,
        created_at: "2026-05-01T00:00:00Z",
      }),
    );

    const { result } = renderHook(() => useUploadDocument(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile(), project_id: "p" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer test-token");
    expect(headers["X-Org-ID"]).toBe("00000000-0000-0000-0000-000000000000");
    // Critical: no manually-set Content-Type. The browser must inject
    // `multipart/form-data; boundary=---webkit...` so the receiving
    // parser knows where each part ends. A regression that hardcoded
    // `Content-Type: application/json` would 415 the request.
    expect(headers["Content-Type"]).toBeUndefined();
  });

  test("non-2xx → mutation rejects with the server's error message", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [{ message: "file_too_large", code: "413", field: null }],
        }),
        { status: 413, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useUploadDocument(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile(), project_id: "p" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("file_too_large");
  });

  test("non-2xx with empty body → falls back to 'Upload failed (NNN)'", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 502 }));

    const { result } = renderHook(() => useUploadDocument(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile(), project_id: "p" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain("502");
  });
});
