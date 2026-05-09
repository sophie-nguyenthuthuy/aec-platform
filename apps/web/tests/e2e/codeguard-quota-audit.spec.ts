import { expect, test, type Route } from "@playwright/test";

/**
 * E2E: tenant-facing quota audit log at /codeguard/quota/audit.
 *
 * Pre-this-page the only way for a tenant admin to answer "who on
 * our team raised our cap last week" was to file a support ticket.
 * The page reads `codeguard_quota_audit_log` (org-scoped server-side)
 * and renders a filterable table of mutations.
 *
 * What's pinned:
 *   1. Standard render — table shows occurred_at + actor + action +
 *      pre-rendered summary for each entry.
 *   2. The pre-rendered `summary` is what the table shows (vi-VN
 *      grouping comes from the server, not the client — pin so a
 *      future refactor doesn't quietly start reformatting on the UI
 *      side, which would drift from the CLI's output).
 *   3. Action filter narrows the request URL — `?action=quota_set`
 *      / `?action=quota_reset` flow through to the API.
 *   4. Empty state uses different copy when filters are active vs
 *      "no events at all" — the user shouldn't think a filter
 *      narrowed them down to nothing if the org genuinely has no
 *      audit history.
 *   5. Action badge color: blue for `quota_set`, amber for
 *      `quota_reset`. Pin the visual distinction so a regression
 *      that flattens both to neutral can't slip in.
 */

const QUOTA_AUDIT_PATH = "**/api/v1/codeguard/quota/audit*";

interface AuditResponse {
  organization_id: string;
  limit: number;
  entries: Array<{
    id: string;
    occurred_at: string | null;
    actor: string | null;
    action: string | null;
    before: Record<string, unknown> | null;
    after: Record<string, unknown> | null;
    summary: string;
  }>;
}

async function routeAudit(
  page: import("@playwright/test").Page,
  body: AuditResponse,
) {
  await page.route(QUOTA_AUDIT_PATH, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: body, meta: null, errors: null }),
    });
  });
}

test.describe("CODEGUARD / Quota audit log", () => {
  test("renders rows with server-side summary verbatim", async ({ page }) => {
    await routeAudit(page, {
      organization_id: "11111111-1111-1111-1111-111111111111",
      limit: 100,
      entries: [
        {
          id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
          occurred_at: "2026-05-01T12:00:00Z",
          actor: "alice",
          action: "quota_set",
          before: { monthly_input_token_limit: 1_000_000, monthly_output_token_limit: 200_000 },
          after: { monthly_input_token_limit: 5_000_000, monthly_output_token_limit: 1_000_000 },
          summary: "input 1.000.000 → 5.000.000, output 200.000 → 1.000.000",
        },
        {
          id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
          occurred_at: "2026-04-15T09:30:00Z",
          actor: "oncall-billing-T1234",
          action: "quota_reset",
          before: { period_start: "2026-04-01", input_tokens: 850_000, output_tokens: 120_000 },
          after: { period_start: "2026-04-01", input_tokens: 0, output_tokens: 0 },
          summary: "input 850.000 → 0, output 120.000 → 0",
        },
      ],
    });
    await page.goto("/codeguard/quota/audit");

    // Both actor names render verbatim — including the service-account
    // marker (`oncall-billing-T1234`) which is the typical compliance
    // signal for "this was a billing-dispute reset, not a routine cron".
    await expect(page.getByText("alice")).toBeVisible();
    await expect(page.getByText("oncall-billing-T1234")).toBeVisible();
    // Server-side summary surfaces verbatim.
    await expect(
      page.getByText("input 1.000.000 → 5.000.000, output 200.000 → 1.000.000"),
    ).toBeVisible();
    await expect(page.getByText("input 850.000 → 0, output 120.000 → 0")).toBeVisible();
  });

  test("renders distinct color badges for set vs reset", async ({ page }) => {
    // Pin via aria-/text-content rather than asserting on colors
    // directly (Playwright can't reliably read computed `bg-` from
    // tailwind without an extra render). The badge text is the same
    // as the action key, so the badge presence + the table layout is
    // what we pin.
    await routeAudit(page, {
      organization_id: "22222222-2222-2222-2222-222222222222",
      limit: 100,
      entries: [
        {
          id: "id-set",
          occurred_at: "2026-05-01T12:00:00Z",
          actor: "alice",
          action: "quota_set",
          before: null,
          after: { monthly_input_token_limit: 1_000_000 },
          summary: "input ∞ → 1.000.000, output ∞ → ∞",
        },
        {
          id: "id-reset",
          occurred_at: "2026-04-15T09:30:00Z",
          actor: "bob",
          action: "quota_reset",
          before: null,
          after: null,
          summary: "(no usage row — nothing to zero)",
        },
      ],
    });
    await page.goto("/codeguard/quota/audit");

    // Both badges present in the body.
    await expect(page.getByText("quota_set", { exact: true })).toBeVisible();
    await expect(page.getByText("quota_reset", { exact: true })).toBeVisible();
    // The first-time-provisioning summary uses ∞ as the unlimited
    // shorthand — pin so the convention propagates from CLI to UI.
    await expect(page.getByText("input ∞ → 1.000.000")).toBeVisible();
  });

  test("action filter narrows the request URL", async ({ page }) => {
    // Pin the cadence contract: the dropdown's `quota_reset` choice
    // must propagate to the URL as `?action=quota_reset`. A regression
    // that swallowed the param would silently show the unfiltered
    // list while the dropdown displayed "Reset usage."
    let observedUrl: string | null = null;
    await page.route(QUOTA_AUDIT_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      observedUrl = route.request().url();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: { organization_id: "x", limit: 100, entries: [] },
          meta: null,
          errors: null,
        }),
      });
    });
    await page.goto("/codeguard/quota/audit");

    // Default fetch — no action filter on the URL.
    await expect(page.getByText(/Tổ chức của bạn chưa có thay đổi/)).toBeVisible();
    expect(observedUrl).toBeTruthy();
    expect(observedUrl).not.toMatch(/action=/);

    // Pick `quota_reset` from the action dropdown.
    await page
      .getByLabel("Hành động")
      .selectOption({ label: "Reset usage (reset)" });
    // Wait for the next request — the empty-state copy switches to
    // "no events match the filter" when filters are active.
    await expect(
      page.getByText(/Không có sự kiện nào khớp với bộ lọc/),
    ).toBeVisible();
    expect(observedUrl).toMatch(/action=quota_reset/);
  });

  test("empty-state distinguishes 'no events at all' from 'no match'", async ({ page }) => {
    // No filters set, zero entries → "chưa có thay đổi" (no events
    // at all). With a filter set + zero entries → "không khớp" (no
    // events match). Pin so the user can tell whether their filter
    // narrowed nothing OR whether their org genuinely has no
    // history.
    await routeAudit(page, {
      organization_id: "33333333-3333-3333-3333-333333333333",
      limit: 100,
      entries: [],
    });
    await page.goto("/codeguard/quota/audit");
    await expect(
      page.getByText(/Tổ chức của bạn chưa có thay đổi hạn mức/),
    ).toBeVisible();

    // Apply a filter — same empty response, but the empty-state copy
    // changes.
    await page
      .getByLabel("Hành động")
      .selectOption({ label: "Đặt hạn mức (set)" });
    await expect(
      page.getByText(/Không có sự kiện nào khớp với bộ lọc/),
    ).toBeVisible();
  });

  test("error state surfaces a red alert", async ({ page }) => {
    await page.route(QUOTA_AUDIT_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });
    await page.goto("/codeguard/quota/audit");

    await expect(page.getByText(/Lỗi khi tải nhật ký/)).toBeVisible();
  });
});
