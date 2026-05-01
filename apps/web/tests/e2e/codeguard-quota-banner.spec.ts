import { expect, test, type Route } from "@playwright/test";

/**
 * E2E: per-org quota status banner in the codeguard layout.
 *
 * Coverage matrix — what should render at each usage band:
 *   <80%        : nothing (banner hidden)
 *   80-95%      : amber "approaching cap" warning, progress bar
 *   95%+        : red "imminent" warning, progress bar
 *   unlimited   : nothing (no quota row, or NULL on every dimension)
 *
 * Plus the "binding dimension" rule: when both input and output have
 * percents, the higher one is what the banner shows. A regression that
 * picked the *lower* would silently under-warn a user pinned on output
 * (the dimension Anthropic prices ~5x higher), which is exactly the
 * case the banner exists to surface.
 */

const QUOTA_PATH_GLOB = "**/api/v1/codeguard/quota";

interface QuotaResponse {
  organization_id: string;
  unlimited: boolean;
  input: { used: number; limit: number | null; percent: number | null } | null;
  output: { used: number; limit: number | null; percent: number | null } | null;
  period_start: string | null;
}

function fulfillQuota(quota: QuotaResponse) {
  return async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: quota, meta: null, errors: null }),
    });
  };
}

test.describe("CODEGUARD / QuotaStatusBanner", () => {
  test("hides banner under 80% on both dimensions", async ({ page }) => {
    await page.route(
      QUOTA_PATH_GLOB,
      fulfillQuota({
        organization_id: "11111111-1111-1111-1111-111111111111",
        unlimited: false,
        input: { used: 200_000, limit: 1_000_000, percent: 20.0 },
        output: { used: 50_000, limit: 200_000, percent: 25.0 },
        period_start: "2026-05-01",
      }),
    );
    await page.goto("/codeguard/regulations");

    // Pinned: nothing in either palette renders. Use role="status"
    // since the banner is the only one in the codeguard layout.
    await expect(page.getByRole("status")).toHaveCount(0);
  });

  test("hides banner for unlimited orgs (no quota row)", async ({ page }) => {
    await page.route(
      QUOTA_PATH_GLOB,
      fulfillQuota({
        organization_id: "22222222-2222-2222-2222-222222222222",
        unlimited: true,
        input: null,
        output: null,
        period_start: null,
      }),
    );
    await page.goto("/codeguard/regulations");

    await expect(page.getByRole("status")).toHaveCount(0);
  });

  test("renders amber warning at 85%", async ({ page }) => {
    await page.route(
      QUOTA_PATH_GLOB,
      fulfillQuota({
        organization_id: "33333333-3333-3333-3333-333333333333",
        unlimited: false,
        input: { used: 850_000, limit: 1_000_000, percent: 85.0 },
        output: { used: 100_000, limit: 200_000, percent: 50.0 },
        period_start: "2026-05-01",
      }),
    );
    await page.goto("/codeguard/regulations");

    // Amber palette → "Đã dùng X% hạn mức input trong tháng" copy.
    await expect(page.getByRole("status")).toBeVisible();
    await expect(page.getByText(/Đã dùng 85\.0% hạn mức input/)).toBeVisible();
    // Token counts surface verbatim.
    await expect(page.getByText(/850\.000\s*\/\s*1\.000\.000/)).toBeVisible();
    // Progress bar exists with correct aria value.
    const bar = page.getByRole("progressbar");
    await expect(bar).toBeVisible();
    await expect(bar).toHaveAttribute("aria-valuenow", "85");
  });

  test("renders red 'imminent' warning at 96%", async ({ page }) => {
    await page.route(
      QUOTA_PATH_GLOB,
      fulfillQuota({
        organization_id: "44444444-4444-4444-4444-444444444444",
        unlimited: false,
        input: { used: 200_000, limit: 1_000_000, percent: 20.0 },
        output: { used: 192_000, limit: 200_000, percent: 96.0 },
        period_start: "2026-05-01",
      }),
    );
    await page.goto("/codeguard/regulations");

    // Red palette uses the "Sắp đạt" / "imminent" copy. Output is the
    // binding dimension here — output 96% > input 20%.
    await expect(page.getByRole("status")).toBeVisible();
    await expect(page.getByText(/Sắp đạt hạn mức tháng — output/)).toBeVisible();
    const bar = page.getByRole("progressbar");
    await expect(bar).toHaveAttribute("aria-valuenow", "96");
  });

  test("picks the higher-percent dimension when both are configured", async ({
    page,
  }) => {
    // Output at 90% is the binding dimension here, even though input
    // (60%) is the larger raw token cap. Regression check: a banner
    // that picked input would silently miss the at-risk dimension.
    await page.route(
      QUOTA_PATH_GLOB,
      fulfillQuota({
        organization_id: "55555555-5555-5555-5555-555555555555",
        unlimited: false,
        input: { used: 6_000_000, limit: 10_000_000, percent: 60.0 },
        output: { used: 180_000, limit: 200_000, percent: 90.0 },
        period_start: "2026-05-01",
      }),
    );
    await page.goto("/codeguard/regulations");

    // Banner renders with output as the dimension label, 90.0% as the
    // surfaced percent.
    await expect(page.getByText(/Đã dùng 90\.0% hạn mức output/)).toBeVisible();
    // Critically, NOT the input dimension's text.
    await expect(page.getByText(/Đã dùng 60\.0%/)).toHaveCount(0);
  });

  test("hides banner when one dimension is null and the other is under threshold", async ({
    page,
  }) => {
    // Input unlimited, output at 50% — below the 80% warn threshold,
    // so the banner stays hidden. Pin the contract: a null input must
    // not be coerced to 0% and accidentally displayed as "0% used."
    await page.route(
      QUOTA_PATH_GLOB,
      fulfillQuota({
        organization_id: "66666666-6666-6666-6666-666666666666",
        unlimited: false,
        input: { used: 999_999, limit: null, percent: null },
        output: { used: 100_000, limit: 200_000, percent: 50.0 },
        period_start: "2026-05-01",
      }),
    );
    await page.goto("/codeguard/regulations");

    await expect(page.getByRole("status")).toHaveCount(0);
  });
});
