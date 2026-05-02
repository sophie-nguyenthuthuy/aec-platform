import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useGenerateProposal } from "@/hooks/winwork/useGenerateProposal";

import { envelopeResponse, makeWrapper } from "./_harness";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useGenerateProposal / contract", () => {
  test("POSTs the request payload to /winwork/proposals/generate", async () => {
    fetchMock.mockResolvedValue(
      envelopeResponse({
        proposal: {
          id: "prop-1",
          project_id: null,
          title: "Marina Tower fit-out",
          status: "draft",
          client_name: null,
          client_email: null,
          scope_of_work: null,
          fee_breakdown: null,
          total_fee_vnd: null,
          total_fee_currency: "VND",
          valid_until: null,
          ai_generated: true,
          ai_confidence: 0.82,
          notes: null,
          sent_at: null,
          responded_at: null,
          created_by: null,
          created_at: "2026-05-01T00:00:00Z",
        },
        ai_job_id: "job-1",
      }),
    );

    const { result } = renderHook(() => useGenerateProposal(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_type: "residential",
      area_sqm: 1200,
      floors: 8,
      location: "HCMC, District 1",
      scope_items: ["interior_design", "mep_coordination"],
      client_brief: "Premium residential interior fit-out across 8 floors.",
      discipline: "architecture",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url as string).pathname).toBe(
      "/api/v1/winwork/proposals/generate",
    );
    expect((init as RequestInit).method).toBe("POST");

    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      project_type: "residential",
      area_sqm: 1200,
      floors: 8,
      location: "HCMC, District 1",
      scope_items: ["interior_design", "mep_coordination"],
      client_brief: "Premium residential interior fit-out across 8 floors.",
      discipline: "architecture",
    });
  });

  test("returns the unwrapped ProposalGenerateResponse on success", async () => {
    const response = {
      proposal: {
        id: "prop-2",
        project_id: null,
        title: "Generated proposal",
        status: "draft" as const,
        client_name: null,
        client_email: null,
        scope_of_work: null,
        fee_breakdown: null,
        total_fee_vnd: 1_000_000_000,
        total_fee_currency: "VND",
        valid_until: null,
        ai_generated: true,
        ai_confidence: 0.9,
        notes: null,
        sent_at: null,
        responded_at: null,
        created_by: null,
        created_at: "2026-05-01T00:00:00Z",
      },
      ai_job_id: "job-2",
    };
    fetchMock.mockResolvedValue(envelopeResponse(response));

    const { result } = renderHook(() => useGenerateProposal(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_type: "office",
      area_sqm: 500,
      floors: 3,
      location: "Hanoi",
      scope_items: ["concept_design"],
      client_brief: "Brief.",
      discipline: "architecture",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(response);
  });

  test("502 from the LLM pipeline surfaces as ApiError, not silent success", async () => {
    // The proposal-generate route returns 502 when the upstream Anthropic
    // call fails (per `apps/api/routers/winwork.py`). The hook must
    // propagate that, not swallow it — otherwise the UI would render an
    // empty proposal as "success."
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: null,
          errors: [{ code: "llm_failure", message: "Anthropic timed out" }],
        }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useGenerateProposal(), {
      wrapper: makeWrapper(),
    });

    result.current.mutate({
      project_type: "office",
      area_sqm: 500,
      floors: 3,
      location: "Hanoi",
      scope_items: ["concept_design"],
      client_brief: "Brief.",
      discipline: "architecture",
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain(
      "Anthropic timed out",
    );
  });
});
