import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useUploadDrawing } from "@/hooks/costpulse/useUploadDrawing";

import { makeWrapper } from "./_harness";

/**
 * useUploadDrawing routes through the shared `/api/v1/files` endpoint
 * with `source_module="costpulse"` (different from drawbridge's dedicated
 * `/documents/upload` route). The return shape adds the file's name
 * back onto the server response — that's a hook-side join, not part
 * of the API contract.
 *
 * Pin:
 *   1. POST `/api/v1/files` (NOT `/costpulse/upload-drawing`).
 *   2. FormData with `source_module=costpulse` baked in.
 *   3. `project_id` only attached when provided (the upload page allows
 *      uploads without a project context — global drawing library).
 *   4. Return shape merges server `data` with the file's `name`.
 */

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const fakeFile = (name = "tower-A-arch.pdf") =>
  new File(["%PDF-1.4 fake"], name, { type: "application/pdf" });

function jsonOk(data: unknown): Response {
  return new Response(JSON.stringify({ data }), {
    status: 201,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useUploadDrawing / contract", () => {
  test("POSTs FormData to /api/v1/files with source_module=costpulse", async () => {
    fetchMock.mockResolvedValue(
      jsonOk({
        file_id: "f-1",
        storage_key: "costpulse/org/file.pdf",
        thumbnail_url: null,
        mime_type: "application/pdf",
        size_bytes: 1234,
      }),
    );

    const { result } = renderHook(() => useUploadDrawing(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile(), project_id: "proj-1" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe("/api/v1/files");
    expect((init as RequestInit).method).toBe("POST");

    const form = (init as RequestInit).body as FormData;
    expect(form.get("source_module")).toBe("costpulse");
    expect(form.get("project_id")).toBe("proj-1");
    expect(form.get("file")).toBeInstanceOf(File);
  });

  test("project_id is omitted when caller doesn't provide one", async () => {
    fetchMock.mockResolvedValue(
      jsonOk({
        file_id: "f-1",
        storage_key: "costpulse/org/file.pdf",
        thumbnail_url: null,
        mime_type: "application/pdf",
        size_bytes: 1,
      }),
    );

    const { result } = renderHook(() => useUploadDrawing(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const form = (fetchMock.mock.calls[0]![1] as RequestInit).body as FormData;
    expect(form.has("project_id")).toBe(false);
  });

  test("return shape merges server data + the file's name", async () => {
    // Hook adds `name: file.name` so the upload UI can render
    // "Concrete-spec.pdf uploaded" without re-reading the input.
    fetchMock.mockResolvedValue(
      jsonOk({
        file_id: "f-1",
        storage_key: "k",
        thumbnail_url: "http://t/1.jpg",
        mime_type: "application/pdf",
        size_bytes: 99,
      }),
    );

    const { result } = renderHook(() => useUploadDrawing(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile("Concrete-spec.pdf") });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual({
      file_id: "f-1",
      storage_key: "k",
      thumbnail_url: "http://t/1.jpg",
      mime_type: "application/pdf",
      size_bytes: 99,
      name: "Concrete-spec.pdf",
    });
  });

  test("non-2xx → throws with server's error message", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ errors: [{ message: "unsupported_mime_type" }] }),
        { status: 415, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useUploadDrawing(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ file: fakeFile() });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("unsupported_mime_type");
  });
});
