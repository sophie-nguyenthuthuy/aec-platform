/**
 * Vitest coverage for the public supplier RFQ-response page.
 *
 * This page is paying customers' first impression of the platform —
 * suppliers click an emailed link and land here without an AEC
 * Platform login. A regression that breaks the loading/expired/form
 * branches embarrasses us at the worst possible moment.
 *
 * Test buckets:
 *   1. Token gating: empty `?t=` → friendly "missing link" copy
 *      (NOT a generic 401 / blank screen).
 *   2. Loading state: shown while context fetch is pending.
 *   3. Expired link: 401 from the API surfaces the right copy
 *      (separate from the generic-error variant).
 *   4. Submitted confirmation: submission_status="submitted" skips
 *      the form and shows the thank-you state.
 *   5. Form render: pending status shows BOQ digest + submit button.
 *   6. Locale toggle: clicking EN flips labels.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import RfqRespondPage from "../page";


// jsdom's `window.location` is normally not directly assignable. We
// install a writable replacement before each test so we can vary
// `?t=` and `?lang=` without `pushState`-shenanigans.
function setLocationSearch(search: string) {
  // `window.location` in jsdom lets us mutate `.search` directly
  // (unlike a real browser where it triggers a navigation). This is
  // a deliberate jsdom quirk we exploit.
  window.history.replaceState({}, "", `/rfq/respond${search}`);
}


function makeContextResponse(
  overrides: Partial<Record<string, unknown>> = {},
): { ok: true; status: number; json: () => Promise<unknown> } {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data: {
        organization_name: "ACME Construction",
        project_name: "Tower 1",
        estimate_name: "Foundation pour",
        deadline: "2026-05-15",
        boq_digest: [
          {
            material_code: "CONC_C30",
            description: "Bê tông C30",
            quantity: "10",
            unit: "m3",
          },
        ],
        submission_status: "pending",
        submitted_quote: null,
        ...overrides,
      },
    }),
  };
}


let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  // Reset the URL between tests so locale + token state doesn't leak.
  window.history.replaceState({}, "", "/rfq/respond");
});


describe("RfqRespondPage / token gating", () => {
  test("missing `?t=` shows the missing-token error card", async () => {
    setLocationSearch("");
    render(<RfqRespondPage />);

    // VN copy by default — `resolveSupplierLocale` falls back to "vi"
    // when no `lang` param is set. Probe by the title key's VN value.
    expect(await screen.findByText(/Liên kết không hợp lệ/)).toBeInTheDocument();

    // Critically, NO fetch was made — no token means no point asking.
    expect(fetchMock).not.toHaveBeenCalled();
  });
});


describe("RfqRespondPage / loading + ready states", () => {
  test("shows loading text before the context fetch resolves", async () => {
    setLocationSearch("?t=valid-token");
    // Pending promise — the loading state is visible until it resolves.
    let resolve!: (v: unknown) => void;
    fetchMock.mockReturnValueOnce(new Promise((r) => { resolve = r; }));

    render(<RfqRespondPage />);

    expect(await screen.findByText(/Đang tải/)).toBeInTheDocument();

    // Resolve the pending fetch so the test cleanup doesn't leak it.
    resolve(makeContextResponse());
  });

  test("renders the BOQ digest + submit button when status=pending", async () => {
    setLocationSearch("?t=valid-token");
    fetchMock.mockResolvedValueOnce(makeContextResponse());

    render(<RfqRespondPage />);

    // The buyer's org name lands in the header.
    expect(await screen.findByText("ACME Construction")).toBeInTheDocument();
    // BOQ row description from the seeded digest. Appears twice on
    // the page — once in the scope-preview table at the top and once
    // in the editable line-items table — `findAllByText` covers both.
    const descriptionMatches = await screen.findAllByText("Bê tông C30");
    expect(descriptionMatches.length).toBeGreaterThanOrEqual(1);
    // Submit button — the primary CTA — must be present and enabled.
    const submitButton = screen.getByRole("button", { name: /Gửi báo giá/i });
    expect(submitButton).toBeEnabled();
  });
});


describe("RfqRespondPage / submitted + error states", () => {
  test("submission_status=submitted shows the confirmation, hides the form", async () => {
    setLocationSearch("?t=valid-token");
    fetchMock.mockResolvedValueOnce(
      makeContextResponse({
        submission_status: "submitted",
        submitted_quote: {
          total_vnd: "12500000",
          lead_time_days: 14,
          valid_until: "2026-06-01",
          notes: "DDP HCMC",
          line_items: [],
        },
      }),
    );

    render(<RfqRespondPage />);

    // VN copy of `submitted_banner` — visible on the confirmation card.
    expect(
      await screen.findByText(/Báo giá của bạn đã được tiếp nhận/),
    ).toBeInTheDocument();
    // The submit button MUST NOT be present — supplier already
    // submitted, the form is gone.
    expect(
      screen.queryByRole("button", { name: /Gửi báo giá/i }),
    ).toBeNull();
  });

  test("API 401 surfaces the expired-link copy (not a generic error)", async () => {
    setLocationSearch("?t=expired-token");
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ errors: [{ message: "Token expired" }] }),
    });

    render(<RfqRespondPage />);

    // The expired-specific title — distinct from the generic
    // unavailable_title — confirms the status branch worked.
    expect(
      await screen.findByText(/Liên kết đã hết hạn hoặc không hợp lệ/),
    ).toBeInTheDocument();
  });

  test("non-401 API failures show the unavailable copy with server message", async () => {
    setLocationSearch("?t=valid-token");
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ errors: [{ message: "RFQ withdrawn" }] }),
    });

    render(<RfqRespondPage />);

    expect(
      await screen.findByText(/Yêu cầu báo giá không khả dụng/),
    ).toBeInTheDocument();
    // The server-supplied message should pass through verbatim — saves
    // ops from having to translate "withdrawn" into i18n every time
    // the API grows a new failure mode.
    expect(await screen.findByText(/RFQ withdrawn/)).toBeInTheDocument();
  });
});


describe("RfqRespondPage / locale toggle", () => {
  test("`?lang=en` renders the English copy", async () => {
    setLocationSearch("?lang=en");

    render(<RfqRespondPage />);

    // EN copy of `missing_token_title` — confirms `resolveSupplierLocale`
    // honored the explicit query param.
    expect(await screen.findByText(/Missing link token/)).toBeInTheDocument();
  });

  test("locale toggle button flips the visible language", async () => {
    setLocationSearch("");

    render(<RfqRespondPage />);

    // Default is VN.
    expect(await screen.findByText(/Liên kết không hợp lệ/)).toBeInTheDocument();

    // The locale toggle row exposes "English" + "Tiếng Việt" buttons.
    const enButton = screen.getByRole("button", { name: /English/i });
    enButton.click();

    // EN copy of the same screen now visible.
    await waitFor(() => {
      expect(screen.getByText(/Missing link token/)).toBeInTheDocument();
    });
  });
});
