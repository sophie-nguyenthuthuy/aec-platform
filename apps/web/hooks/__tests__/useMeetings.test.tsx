import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  useCreateMeetingNote,
  useStructureMeetingNotes,
} from "@/hooks/pulse/useMeetings";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * `useMeetings.ts` exports two mutations only — there is no list-query
 * hook (the meetings page reads through useDashboard). We pin both
 * mutation contracts here:
 *
 *   1. POST /pulse/meeting-notes for raw note creation.
 *   2. POST /pulse/meeting-notes/structure for the LLM-structured
 *      action-item-extraction path. Same response type, different
 *      route — easy to silently swap, so we pin the URL on each.
 *
 * Both mutations resolve null `data` to a thrown error (not silent
 * success), and both invalidate the meetingNotes(project_id) cache on
 * success — pin those two semantics.
 */

function makeNote(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "note-1",
    organization_id: "org-1",
    project_id: "proj-1",
    meeting_date: "2026-05-01",
    attendees: ["PM", "Owner Rep"],
    raw_notes: "Discussed schedule slip on level 3 fitout.",
    ai_structured: null,
    created_by: null,
    created_at: "2026-05-01T00:00:00Z",
    ...overrides,
  };
}

describe("useCreateMeetingNote / contract", () => {
  test("POSTs to /pulse/meeting-notes with the input payload", async () => {
    fetchMock.mockResolvedValue(envelopeResponse(makeNote()));

    const { result } = renderHook(() => useCreateMeetingNote(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "proj-1",
      meeting_date: "2026-05-01",
      attendees: ["PM", "Owner Rep"],
      raw_notes: "Discussed schedule slip on level 3 fitout.",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/pulse/meeting-notes",
    );
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      project_id: "proj-1",
      meeting_date: "2026-05-01",
      attendees: ["PM", "Owner Rep"],
      raw_notes: "Discussed schedule slip on level 3 fitout.",
    });
  });

  test("null data on 200 throws — not silent success with stale UI", async () => {
    // The router contract is "POST returns the created MeetingNote",
    // so `{data: null}` is a backend bug. The hook must surface it as
    // an error so the form shows a retry — otherwise the user sees
    // their note submit "successfully" but never appear in the list.
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ data: null, meta: null, errors: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useCreateMeetingNote(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "proj-1",
      meeting_date: "2026-05-01",
      attendees: [],
      raw_notes: "x",
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain(
      "Create meeting note failed",
    );
  });
});

describe("useStructureMeetingNotes / contract", () => {
  test("POSTs to /pulse/meeting-notes/structure (the LLM path)", async () => {
    // Distinct route from plain create — `/structure` runs the
    // extraction pipeline. Pin the suffix; a regression that pointed
    // it at /pulse/meeting-notes would silently bypass the LLM and
    // store raw text as-is.
    fetchMock.mockResolvedValue(envelopeResponse(makeNote()));

    const { result } = renderHook(() => useStructureMeetingNotes(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_id: "proj-1",
      raw_notes: "Owner asked for two-week schedule recovery plan.",
      language: "vi",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/pulse/meeting-notes/structure",
    );
  });

  test("returns the unwrapped MeetingNote on success", async () => {
    const note = makeNote({
      ai_structured: {
        summary: "Schedule slip discussion.",
        decisions: ["Two-week recovery plan"],
        action_items: [],
        risks: [],
        next_meeting: null,
      },
    });
    fetchMock.mockResolvedValue(envelopeResponse(note));

    const { result } = renderHook(() => useStructureMeetingNotes(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ project_id: "proj-1", raw_notes: "..." });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(note);
  });

  test("null data on 200 throws (not silent success)", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ data: null, meta: null, errors: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useStructureMeetingNotes(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({ project_id: "proj-1", raw_notes: "..." });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain(
      "Structure meeting notes failed",
    );
  });
});
