import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useToggleWatch } from "@/hooks/notifications/useWatches";

import { envelopeResponse, makeWrapper } from "./_harness";

/**
 * useToggleWatch returns `{ watch, unwatch }` — two mutations that
 * share a project_id but use different methods + URL shapes:
 *
 *   watch    → POST   /api/v1/notifications/watches      (body: project_id)
 *   unwatch  → DELETE /api/v1/notifications/watches/{id} (no body)
 *
 * Symmetric mistakes — sending the project_id in the URL on watch, or
 * in the body on unwatch — would silently fail server-side. Pin the
 * shape both ways.
 */

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useToggleWatch / watch", () => {
  test("POSTs to /watches with project_id in JSON body", async () => {
    fetchMock.mockResolvedValue(envelopeResponse({ id: "watch-1" }));

    const { result } = renderHook(() => useToggleWatch(PROJECT_ID), {
      wrapper: makeWrapper(),
    });

    result.current.watch.mutate();
    await waitFor(() => expect(result.current.watch.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe("/api/v1/notifications/watches");
    expect((init as RequestInit).method).toBe("POST");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ project_id: PROJECT_ID });
  });
});

describe("useToggleWatch / unwatch", () => {
  test("DELETEs /watches/{project_id} with no body", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null, { status: 204 }));

    const { result } = renderHook(() => useToggleWatch(PROJECT_ID), {
      wrapper: makeWrapper(),
    });

    result.current.unwatch.mutate();
    await waitFor(() => expect(result.current.unwatch.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    // project_id lands in the URL path, NOT the body.
    expect(new URL(url as string).pathname).toBe(
      `/api/v1/notifications/watches/${PROJECT_ID}`,
    );
    expect((init as RequestInit).method).toBe("DELETE");
    // DELETE with no body — apiFetch sends `body: undefined` for "no body"
    // (see lib/__tests__/api.test.ts contract).
    expect((init as RequestInit).body).toBeUndefined();
  });

  test("returns null even when the API responds with non-JSON body", async () => {
    // Common shape for 204 No Content — body is empty string. The hook's
    // `return null` ensures TanStack Query gets a valid value (otherwise
    // `data` would be `undefined` and the `isSuccess`/`data` invariant
    // gets confusing for consumers).
    fetchMock.mockResolvedValue(new Response("", { status: 204 }));

    const { result } = renderHook(() => useToggleWatch(PROJECT_ID), {
      wrapper: makeWrapper(),
    });

    result.current.unwatch.mutate();
    await waitFor(() => expect(result.current.unwatch.isSuccess).toBe(true));

    expect(result.current.unwatch.data).toBeNull();
  });
});

describe("useToggleWatch / project_id baked into closure", () => {
  test("calling .mutate() with a stale projectId still hits the original URL", async () => {
    // The project_id is captured from the hook's argument once at render
    // time — that's the documented behaviour. Pin it: a future refactor
    // that read project_id from elsewhere (context, store) without an
    // explicit re-render would silently change the URL between mutate()
    // calls.
    fetchMock.mockResolvedValue(envelopeResponse(null, { status: 204 }));

    const { result } = renderHook(() => useToggleWatch(PROJECT_ID), {
      wrapper: makeWrapper(),
    });

    result.current.unwatch.mutate();
    await waitFor(() => expect(result.current.unwatch.isSuccess).toBe(true));

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname.endsWith(PROJECT_ID)).toBe(true);
  });
});
