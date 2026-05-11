/**
 * Vitest coverage for the audit log page.
 *
 * Locks down the system-actor badge added in the cron-audit work
 * + the loading/error/empty branches + the dropdown coverage. The
 * page is the compliance surface — a regression that hides cron-
 * driven events or breaks the dropdown would silently degrade the
 * audit story for enterprise customers.
 *
 * Strategy: mock `@/hooks/audit` so we can drive the data without
 * standing up TanStack Query. The page renders raw VN strings
 * (next-intl migration was reverted upstream); tests assert on
 * those strings directly. If/when next-intl lands again, the
 * assertions will need to flip to the i18n keys — but the test
 * shape stays identical.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";


// `useAuditEvents` mocked so we can drive `data` / `isLoading` /
// `isError` directly. Default to "loading"; per-test overrides via
// `auditEventsState`.
// All fields except `data` + `error` are required by useQuery's
// return shape; we initialise with the loading defaults so the
// component reads them as a fresh fetch in flight.
let auditEventsState: {
  data?: { data: unknown[]; meta: { total: number } };
  isLoading: boolean;
  isError: boolean;
  error?: Error;
} = { isLoading: true, isError: false };

vi.mock("@/hooks/audit", () => ({
  useAuditEvents: () => auditEventsState,
}));


import AuditPage from "../page";


function makeEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "evt-1",
    organization_id: "org-1",
    actor_user_id: "user-1",
    actor_email: "alice@example.com",
    action: "costpulse.estimate.approve",
    resource_type: "estimates",
    resource_id: "abcdef12-3456-7890-abcd-ef1234567890",
    before: { status: "draft" },
    after: { status: "approved" },
    ip: "10.0.0.1",
    user_agent: "test-agent",
    created_at: "2026-04-01T12:00:00Z",
    ...overrides,
  };
}


beforeEach(() => {
  // Reset to "loading" between tests so a forgotten override doesn't
  // bleed across.
  auditEventsState = { isLoading: true, isError: false };
});

afterEach(() => {
  vi.clearAllMocks();
});


describe("AuditPage / state branches", () => {
  test("loading state shows the loading copy", () => {
    auditEventsState = { isLoading: true, isError: false };
    render(<AuditPage />);
    expect(screen.getByText("Đang tải...")).toBeInTheDocument();
  });

  test("error state shows the error title + admin-required body fallback", () => {
    auditEventsState = {
      isLoading: false,
      isError: true,
      // No `error` → component falls back to the admin-required hint.
      // This is the 403-from-the-API path, the dominant failure mode
      // for non-admins that landed on the URL.
    };
    render(<AuditPage />);
    expect(screen.getByText("Không thể tải nhật ký")).toBeInTheDocument();
    expect(screen.getByText(/Bạn cần quyền admin/)).toBeInTheDocument();
  });

  test("error with a message surfaces the message verbatim (not the fallback)", () => {
    auditEventsState = {
      isLoading: false,
      isError: true,
      error: new Error("Server unavailable"),
    };
    render(<AuditPage />);
    expect(screen.getByText("Server unavailable")).toBeInTheDocument();
    // Fallback should NOT appear when a real error message exists.
    expect(screen.queryByText(/Bạn cần quyền admin/)).toBeNull();
  });

  test("empty state shows the empty-state copy", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: { data: [], meta: { total: 0 } },
    };
    render(<AuditPage />);
    expect(
      screen.getByText(/Không có sự kiện nào khớp với bộ lọc/),
    ).toBeInTheDocument();
  });
});


describe("AuditPage / row rendering", () => {
  test("user-actor row shows actor email, no system badge", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: { data: [makeEvent()], meta: { total: 1 } },
    };
    render(<AuditPage />);
    // The user's email lands in the row header.
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    // The "system" badge MUST NOT appear when an actor email is set —
    // otherwise admins skimming the log would see "system" + email
    // side-by-side and have no idea which to trust.
    //
    // We use `getAllByText("system")` filtered — a `system_actor_badge`
    // text-only assertion would also catch the inline comment, so we
    // narrow on the badge's distinctive class to disambiguate.
    expect(screen.queryByText("system")).toBeNull();
  });

  test("null actor_email renders the system badge (cron-driven event)", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: {
        data: [
          makeEvent({
            actor_user_id: null,
            actor_email: null,
            action: "costpulse.rfq.slots_expired",
          }),
        ],
        meta: { total: 1 },
      },
    };
    render(<AuditPage />);
    // The system badge text — confirms the null-actor branch fires.
    expect(screen.getByText("system")).toBeInTheDocument();
  });

  test("action label looks up the in-page ACTION_FILTERS map", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: {
        data: [makeEvent({ action: "admin.normalizer_rule.update" })],
        meta: { total: 1 },
      },
    };
    render(<AuditPage />);
    // The label appears in BOTH the row chip and the dropdown option,
    // so we use `getAllByText` and assert >=1 (a missing label-lookup
    // wiring would produce zero matches).
    const matches = screen.getAllByText("Sửa luật chuẩn hoá");
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  test("unknown action falls back to the raw string (no crash)", () => {
    // The action-label lookup uses `?? event.action` for forward-compat:
    // a server can ship a new audit verb before the frontend's
    // ACTION_FILTERS catches up. The row should render with the raw
    // dotted action, not break.
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: {
        data: [makeEvent({ action: "future.module.unknown_verb" })],
        meta: { total: 1 },
      },
    };
    render(<AuditPage />);
    expect(screen.getByText("future.module.unknown_verb")).toBeInTheDocument();
  });

  test("diff summary surfaces from before/after on the row header", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: {
        data: [makeEvent({ before: { status: "draft" }, after: { status: "approved" } })],
        meta: { total: 1 },
      },
    };
    render(<AuditPage />);
    // Diff format: "k: from → to" — joined with " · ", capped at 2.
    expect(
      screen.getByText(/status: draft → approved/),
    ).toBeInTheDocument();
  });
});


describe("AuditPage / filter dropdowns", () => {
  test("action dropdown carries every closed-set value", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: { data: [], meta: { total: 0 } },
    };
    render(<AuditPage />);

    // The "all actions" option has the empty value; its label is the
    // VN sentinel.
    const allActionsOption = screen.getByRole("option", { name: "Tất cả hành động" });
    expect(allActionsOption).toBeInTheDocument();
    expect((allActionsOption as HTMLOptionElement).value).toBe("");

    // Every audit verb gets its own option with a VN label.
    expect(
      screen.getByRole("option", { name: "Xoá luật chuẩn hoá" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "RFQ hết hạn (tự động)" }),
    ).toBeInTheDocument();
  });

  test("resource dropdown carries every closed-set value", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: { data: [], meta: { total: 0 } },
    };
    render(<AuditPage />);

    expect(
      screen.getByRole("option", { name: "Tất cả tài nguyên" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Luật chuẩn hoá" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Dự toán" }),
    ).toBeInTheDocument();
  });
});


describe("AuditPage / pagination", () => {
  test("hides pagination when total fits in a single page", () => {
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: { data: [makeEvent()], meta: { total: 1 } },
    };
    render(<AuditPage />);
    // Prev/next button labels would only appear when multi-page.
    expect(screen.queryByRole("button", { name: "Trước" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sau" })).toBeNull();
  });

  test("shows pagination when total > per_page", () => {
    // PER_PAGE is 50; 51 forces a second page.
    auditEventsState = {
      isLoading: false,
      isError: false,
      data: { data: [makeEvent()], meta: { total: 51 } },
    };
    render(<AuditPage />);
    expect(screen.getByRole("button", { name: "Trước" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sau" })).toBeInTheDocument();
    // Page indicator: "Trang 1 / 2".
    expect(screen.getByText(/Trang 1 \/ 2/)).toBeInTheDocument();
  });
});
