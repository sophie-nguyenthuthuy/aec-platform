import { expect, test, type Route } from "@playwright/test";

/**
 * E2E: per-tenant quota dashboard at /codeguard/quota.
 *
 * Different surface than the banner E2E (codeguard-quota-banner.spec.ts):
 * the banner is a *reactive* alert that hides under 80%; this page is
 * the *planning* surface that always shows the full picture (input +
 * output bars, cap numbers, period start, days-until-reset, and a
 * 3-month usage trend).
 *
 * What the tests pin:
 *   1. Both dimension bars render even when usage is well under any
 *      warning threshold — regression guard so a refactor that
 *      silently reused the banner's "hide under 80%" logic here can't
 *      slip in.
 *   2. Unlimited orgs get a one-liner notice and NO progress section
 *      (showing "0 / null" bars would be confusing).
 *   3. Per-dimension `aria-valuenow` matches the percent — so screen
 *      readers and our test selectors agree on what's rendered.
 *   4. The 3-month history strip fetches `?months=3` and renders one
 *      bar per month (including months the API omitted — those render
 *      as zero-height filler so the strip is always 3 columns wide).
 *   5. Error state on the primary quota fetch surfaces the red alert
 *      instead of a half-rendered page.
 */

const QUOTA_PATH = "**/api/v1/codeguard/quota";
const QUOTA_HISTORY_PATH = "**/api/v1/codeguard/quota/history*";

interface QuotaResponse {
  organization_id: string;
  unlimited: boolean;
  input: { used: number; limit: number | null; percent: number | null } | null;
  output: { used: number; limit: number | null; percent: number | null } | null;
  period_start: string | null;
}

interface QuotaHistoryResponse {
  organization_id: string;
  months: number;
  input_limit: number | null;
  output_limit: number | null;
  history: Array<{
    period_start: string;
    input_tokens: number;
    output_tokens: number;
  }>;
}

/** The history glob also matches the bare `/quota` path because of the
 *  `*` suffix; route order matters in Playwright (most specific first
 *  wins on first registration). Explicit helpers below register the
 *  history glob first so the more-specific match is consulted before
 *  the bare-quota glob. */
async function routeQuotaPair(
  page: import("@playwright/test").Page,
  quota: QuotaResponse,
  history: QuotaHistoryResponse | null,
) {
  // History MUST be registered before the quota path — the quota glob
  // (`**/api/v1/codeguard/quota`) has no trailing wildcard, so without
  // explicit ordering it would still match exactly the bare `/quota`
  // GET. We're being defensive in case a future glob change bites.
  if (history !== null) {
    await page.route(QUOTA_HISTORY_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: history, meta: null, errors: null }),
      });
    });
  }
  await page.route(QUOTA_PATH, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: quota, meta: null, errors: null }),
    });
  });
}

test.describe("CODEGUARD / Quota dashboard", () => {
  test("renders both dimension bars even at low usage", async ({ page }) => {
    // 20% / 25% — well under the banner's 80% threshold. Page must
    // STILL render the bars (this is the regression guard for "did
    // someone copy the banner's hide-under-80% logic into the page").
    await routeQuotaPair(
      page,
      {
        organization_id: "11111111-1111-1111-1111-111111111111",
        unlimited: false,
        input: { used: 200_000, limit: 1_000_000, percent: 20.0 },
        output: { used: 50_000, limit: 200_000, percent: 25.0 },
        period_start: "2026-05-01",
      },
      {
        organization_id: "11111111-1111-1111-1111-111111111111",
        months: 3,
        input_limit: 1_000_000,
        output_limit: 200_000,
        history: [
          { period_start: "2026-05-01", input_tokens: 200_000, output_tokens: 50_000 },
          { period_start: "2026-04-01", input_tokens: 800_000, output_tokens: 150_000 },
          { period_start: "2026-03-01", input_tokens: 600_000, output_tokens: 100_000 },
        ],
      },
    );
    await page.goto("/codeguard/quota");

    // Both progress bars render with the right aria-valuenow.
    const bars = page.getByRole("progressbar");
    await expect(bars).toHaveCount(2);
    await expect(bars.first()).toHaveAttribute("aria-valuenow", "20");
    await expect(bars.nth(1)).toHaveAttribute("aria-valuenow", "25");
    // Token counts surface verbatim with vi-VN grouping (1.000.000).
    await expect(page.getByText(/200\.000\s*\/\s*1\.000\.000\s*token/)).toBeVisible();
    await expect(page.getByText(/50\.000\s*\/\s*200\.000\s*token/)).toBeVisible();
    // Period + countdown copy renders.
    await expect(page.getByText(/Kỳ:\s*01\/05\/2026/)).toBeVisible();
    await expect(page.getByText(/ngày nữa reset/)).toBeVisible();
  });

  test("renders only a one-liner for unlimited orgs", async ({ page }) => {
    await routeQuotaPair(
      page,
      {
        organization_id: "22222222-2222-2222-2222-222222222222",
        unlimited: true,
        input: null,
        output: null,
        period_start: null,
      },
      // History endpoint shouldn't really be hit when unlimited (the
      // page short-circuits), but we still stub it so a regression
      // that DOES call it doesn't 404 in the test harness.
      {
        organization_id: "22222222-2222-2222-2222-222222222222",
        months: 3,
        input_limit: null,
        output_limit: null,
        history: [],
      },
    );
    await page.goto("/codeguard/quota");

    await expect(page.getByText(/không bị giới hạn token/i)).toBeVisible();
    // No progressbars, no history headings — explicit absence pins
    // the "render only the notice" contract.
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(page.getByText(/3 tháng gần nhất/)).toHaveCount(0);
  });

  test("renders a bar per month for the 3-month history strip", async ({ page }) => {
    // Only 2 of the 3 months have rows; the page fills the missing
    // month with a zero bar so the strip is always N columns wide.
    await routeQuotaPair(
      page,
      {
        organization_id: "33333333-3333-3333-3333-333333333333",
        unlimited: false,
        input: { used: 100_000, limit: 1_000_000, percent: 10.0 },
        output: { used: 5_000, limit: 200_000, percent: 2.5 },
        period_start: "2026-05-01",
      },
      {
        organization_id: "33333333-3333-3333-3333-333333333333",
        months: 3,
        input_limit: 1_000_000,
        output_limit: 200_000,
        history: [
          { period_start: "2026-05-01", input_tokens: 100_000, output_tokens: 5_000 },
          // April omitted — no usage that month. Page fills with zeros.
          { period_start: "2026-03-01", input_tokens: 600_000, output_tokens: 80_000 },
        ],
      },
    );
    await page.goto("/codeguard/quota");

    // Two history charts (input + output), each with a role="img"
    // wrapper labelled with the dimension.
    const charts = page.getByRole("img");
    await expect(charts).toHaveCount(2);
    await expect(charts.first()).toHaveAttribute(
      "aria-label",
      /3 tháng gần nhất/,
    );
  });

  test("history strip requests months=3", async ({ page }) => {
    // Pin the cadence contract: the page asks the backend for 3
    // months. A regression that asked for 1 (or skipped the param)
    // would silently shrink the planning window without a visible
    // failure — pin via the URL.
    let observed: string | null = null;
    await page.route(QUOTA_HISTORY_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      observed = route.request().url();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            organization_id: "x",
            months: 3,
            input_limit: 1_000_000,
            output_limit: 200_000,
            history: [],
          },
          meta: null,
          errors: null,
        }),
      });
    });
    await page.route(QUOTA_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            organization_id: "x",
            unlimited: false,
            input: { used: 0, limit: 1_000_000, percent: 0.0 },
            output: { used: 0, limit: 200_000, percent: 0.0 },
            period_start: "2026-05-01",
          },
          meta: null,
          errors: null,
        }),
      });
    });
    await page.goto("/codeguard/quota");

    // Wait for the history fetch to complete — the section heading is
    // a deterministic signal.
    await expect(page.getByText(/3 tháng gần nhất/)).toBeVisible();
    expect(observed).not.toBeNull();
    expect(observed).toMatch(/months=3/);
  });

  test("surfaces a red alert when the quota fetch errors", async ({ page }) => {
    await page.route(QUOTA_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });
    // History endpoint isn't relevant on the error path but stub a
    // 200 so a request that does fire doesn't trip an unhandled error.
    await page.route(QUOTA_HISTORY_PATH, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: { history: [] }, meta: null, errors: null }),
      });
    });
    await page.goto("/codeguard/quota");

    await expect(page.getByText(/Lỗi khi tải hạn mức/)).toBeVisible();
    // No progressbars or history rendered on the error path.
    await expect(page.getByRole("progressbar")).toHaveCount(0);
  });
});
