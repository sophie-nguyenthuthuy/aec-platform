import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  useCreateNormalizerRule,
  useDeleteNormalizerRule,
  useNormalizerRules,
  useUpdateNormalizerRule,
} from "@/hooks/admin/useNormalizerRules";

import { envelopeResponse, makeWrapper } from "../../__tests__/_harness";

/**
 * Pin the wire contract for the normalizer-rules CRUD hooks.
 *
 * The normalizer-rules editor is the second-most-used admin page
 * (after the scrapers dashboard). When ops sees a slug drifting,
 * the next click is "go add a regex rule." A typo in any of these
 * mutations breaks the only path ops has to fix drift without a
 * deploy.
 *
 * What this catches:
 *
 *   * URL drift on list (`GET`), create (`POST`), update (`PATCH /<id>`),
 *     delete (`DELETE /<id>`). The PATCH+DELETE forms put the
 *     `id` in the path; a regression that put it in the body would
 *     silently 404.
 *
 *   * Method drift — POST is the create, PATCH is the partial
 *     update. A swap (PUT instead of PATCH) would silently fail
 *     server-side because the route declares PATCH.
 *
 *   * Body-shape preservation — create body MUST include the
 *     required {priority, pattern, material_code, canonical_name}.
 *     PATCH body MUST be partial-shaped (omitting unset fields)
 *     so a single-field edit doesn't blank out the rest.
 *
 *   * Cache invalidation — successful mutations invalidate the
 *     list query; otherwise the editor's table stays stale until
 *     the user manually refreshes.
 */

const RULES_PATH = "/api/v1/admin/normalizer-rules";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// ---------- List ----------


describe("useNormalizerRules / list", () => {
  test("GETs the documented admin path", async () => {
    fetchMock.mockResolvedValue(envelopeResponse([]));

    const { result } = renderHook(() => useNormalizerRules(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(RULES_PATH);
    expect((init as RequestInit).method ?? "GET").toBe("GET");
  });

  test("returns the rules array from envelope.data", async () => {
    const rules = [
      {
        id: "rule-1",
        priority: 100,
        pattern: "(?i)bê tông",
        material_code: "CONCRETE_M300",
        category: "concrete",
        canonical_name: "Bê tông M300",
        preferred_units: "m3",
        enabled: true,
        created_at: "2026-05-05T12:00:00Z",
        updated_at: "2026-05-05T12:00:00Z",
      },
    ];
    fetchMock.mockResolvedValue(envelopeResponse(rules));

    const { result } = renderHook(() => useNormalizerRules(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(rules);
  });

  test("returns [] when envelope.data is null", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useNormalizerRules(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // The editor's table calls `.map((rule) => ...)` so a `null`
    // here would crash the render rather than rendering an empty
    // state. Pin the normalisation.
    expect(result.current.data).toEqual([]);
  });
});


// ---------- Create ----------


describe("useCreateNormalizerRule / mutation", () => {
  test("POSTs to /admin/normalizer-rules with the body verbatim", async () => {
    const created = {
      id: "rule-2",
      priority: 200,
      pattern: "(?i)thép tròn",
      material_code: "REBAR_D10",
      category: "steel",
      canonical_name: "Thép tròn D10",
      preferred_units: "kg",
      enabled: true,
      created_at: "2026-05-05T12:00:00Z",
      updated_at: "2026-05-05T12:00:00Z",
    };
    fetchMock.mockResolvedValue(envelopeResponse(created));

    const { result } = renderHook(() => useCreateNormalizerRule(), {
      wrapper: makeWrapper(),
    });

    const payload = {
      priority: 200,
      pattern: "(?i)thép tròn",
      material_code: "REBAR_D10",
      canonical_name: "Thép tròn D10",
    };
    result.current.mutate(payload);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(RULES_PATH);
    expect((init as RequestInit).method).toBe("POST");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual(payload);
  });

  test("returns the created rule from the envelope", async () => {
    const created = {
      id: "rule-3",
      priority: 300,
      pattern: "(?i)cát vàng",
      material_code: "SAND_YELLOW",
      category: null,
      canonical_name: "Cát vàng",
      preferred_units: "m3",
      enabled: true,
      created_at: "2026-05-05T12:00:00Z",
      updated_at: "2026-05-05T12:00:00Z",
    };
    fetchMock.mockResolvedValue(envelopeResponse(created));

    const { result } = renderHook(() => useCreateNormalizerRule(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      priority: 300,
      pattern: "(?i)cát vàng",
      material_code: "SAND_YELLOW",
      canonical_name: "Cát vàng",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(created);
  });
});


// ---------- Update ----------


describe("useUpdateNormalizerRule / mutation", () => {
  test("PATCHes /admin/normalizer-rules/{id} with the partial body", async () => {
    const updated = {
      id: "rule-1",
      priority: 100,
      pattern: "(?i)bê tông M300|(?i)BT M300",
      material_code: "CONCRETE_M300",
      category: "concrete",
      canonical_name: "Bê tông M300",
      preferred_units: "m3",
      enabled: true,
      created_at: "2026-05-05T12:00:00Z",
      updated_at: "2026-05-06T08:00:00Z",
    };
    fetchMock.mockResolvedValue(envelopeResponse(updated));

    const { result } = renderHook(() => useUpdateNormalizerRule(), {
      wrapper: makeWrapper(),
    });

    // Partial: only the pattern is changing.
    result.current.mutate({
      id: "rule-1",
      pattern: "(?i)bê tông M300|(?i)BT M300",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(`${RULES_PATH}/rule-1`);
    expect((init as RequestInit).method).toBe("PATCH");

    const body = JSON.parse((init as RequestInit).body as string);
    // CRITICAL: `id` MUST be in the URL path, NOT the body. The
    // server's PATCH route reads from path params; sending the id
    // in the body would silently apply the patch to the URL-id'd
    // row but include the body-id in the SET clause (no-op or
    // worst-case constraint violation).
    expect(body).toEqual({ pattern: "(?i)bê tông M300|(?i)BT M300" });
    expect(body.id).toBeUndefined();
  });

  test("partial body omits unset fields entirely (no 'undefined' marshalling)", async () => {
    fetchMock.mockResolvedValue(envelopeResponse({} as never));

    const { result } = renderHook(() => useUpdateNormalizerRule(), {
      wrapper: makeWrapper(),
    });

    // Toggle only `enabled=false` — every other field MUST stay out
    // of the body. A regression that sent `pattern: undefined` would
    // get JSON-stringified as `"pattern":null` and the server's
    // partial-update logic would clobber the existing pattern with NULL.
    result.current.mutate({ id: "rule-1", enabled: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [, init] = fetchMock.mock.calls[0]!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ enabled: false });
    expect("pattern" in body).toBe(false);
    expect("priority" in body).toBe(false);
    expect("material_code" in body).toBe(false);
  });
});


// ---------- Delete ----------


describe("useDeleteNormalizerRule / mutation", () => {
  test("DELETEs /admin/normalizer-rules/{id} with no body", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(null));

    const { result } = renderHook(() => useDeleteNormalizerRule(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate("rule-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(`${RULES_PATH}/rule-1`);
    expect((init as RequestInit).method).toBe("DELETE");
    // DELETE with no body — apiFetch sends `body: undefined` for
    // "no body" (see lib/__tests__/api.test.ts contract).
    expect((init as RequestInit).body).toBeUndefined();
  });
});
