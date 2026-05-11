import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useTasks } from "@/hooks/pulse/useTasks";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useTasks / contract", () => {
  test("GETs /pulse/tasks with no filter params when called with default {}", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useTasks(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toBe("/api/v1/pulse/tasks");
    // Unlike useTenders/useDocuments, useTasks intentionally does NOT
    // inject a default limit — the dashboard widget paginates server-
    // side via project_id + status filters, and a hardcoded default
    // here would silently cap the count it shows. Pin it so a future
    // "be consistent with sibling hooks" refactor doesn't regress.
    expect(url.searchParams.has("limit")).toBe(false);
    expect(url.searchParams.has("offset")).toBe(false);
  });

  test("filter params (project_id, status, phase, assignee_id) feed through to the URL", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () =>
        useTasks({
          project_id: "proj-1",
          status: "in_progress",
          phase: "design",
          assignee_id: "user-1",
        }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get("project_id")).toBe("proj-1");
    expect(url.searchParams.get("status")).toBe("in_progress");
    expect(url.searchParams.get("phase")).toBe("design");
    expect(url.searchParams.get("assignee_id")).toBe("user-1");
  });

  test("undefined filters are omitted (not sent as the literal string 'undefined')", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(
      () => useTasks({ project_id: "p", status: undefined, phase: undefined }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.has("project_id")).toBe(true);
    expect(url.searchParams.has("status")).toBe(false);
    expect(url.searchParams.has("phase")).toBe(false);
  });

  test("data is unwrapped from envelope; null data falls back to []", async () => {
    // The board renders `tasks?.length` in headers — if the hook ever
    // returned `null` instead of `[]` on a backend that envelopes to
    // `{data: null}`, the UI would crash. Pin the empty-array fallback.
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ data: null, meta: null, errors: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useTasks(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([]);
  });

  test("cache key changes with filters → re-fetch (filters are part of the queryKey)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const wrapper = makeWrapper();
    const { result, rerender } = renderHook(
      ({ status }: { status?: "todo" | "in_progress" }) => useTasks({ status }),
      // Cast initialProps to the broadened union — without it tsc infers
      // the prop type as `{ status: "todo" }` (narrowed from `as const`),
      // which then makes the later `rerender({ status: "in_progress" })`
      // a "not assignable" error.
      {
        wrapper,
        initialProps: { status: "todo" } as { status?: "todo" | "in_progress" },
      },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ status: "in_progress" });
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(2));

    const first = new URL(fetchMock.mock.calls[0]![0] as string);
    const second = new URL(fetchMock.mock.calls[1]![0] as string);
    expect(first.searchParams.get("status")).toBe("todo");
    expect(second.searchParams.get("status")).toBe("in_progress");
  });
});
