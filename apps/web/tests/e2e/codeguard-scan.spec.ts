import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD compliance scan wizard.
 *
 * What's covered
 * --------------
 * 1. Happy-path wizard — fill params, advance to review, run scan, see the
 *    ComplianceScore donut + per-finding cards (FAIL / WARN / PASS) with
 *    embedded citations. The POST body matches what was filled in.
 * 2. Empty-findings advisory — when the backend returns
 *    `findings: [], total: 0`, the UI must render the amber "Không có vấn
 *    đề nào được nêu" card (NOT the slate "all clear" banner from the
 *    pre-parity revision). Mirror of the query page's abstain treatment:
 *    "we found nothing" should look advisory, not reassuring.
 * 3. Error path — when the mutation rejects (e.g. backend 502 because the
 *    LLM pipeline failed), the results step shows a red error banner
 *    rather than stranding the user in the review step with no feedback.
 *
 * The wizard is multi-step (params → review → results) so the happy-path
 * test walks through all three; the error and empty tests skip directly
 * to the scan trigger and just assert what renders in step 3.
 */

const PROJECT_ID = "44444444-4444-4444-4444-444444444444";

async function fillParamsAndContinue(page: Page) {
  await page.goto("/codeguard/scan");
  await page.getByPlaceholder("UUID").fill(PROJECT_ID);
  // Default project_type=residential is already selected; that's fine
  // for these tests since we're not asserting on it.
  await page.getByRole("button", { name: /tiếp tục/i }).click();
  // We're now on the review step — wait for it to render.
  await expect(page.getByRole("button", { name: /bắt đầu quét/i })).toBeVisible();
}

test.describe("CODEGUARD / Scan", () => {
  test("runs a scan and renders findings with grounded citations", async ({ page }) => {
    let lastBody: unknown = null;

    await page.route("**/api/v1/codeguard/scan", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            check_id: "55555555-5555-5555-5555-555555555555",
            status: "completed",
            total: 2,
            pass_count: 1,
            warn_count: 0,
            fail_count: 1,
            findings: [
              {
                status: "FAIL",
                severity: "critical",
                category: "fire_safety",
                title: "Số lối thoát nạn dưới yêu cầu",
                description:
                  "Dự án 6 tầng chỉ có 1 lối thoát nạn, thấp hơn yêu cầu tối thiểu 2 lối.",
                resolution: "Bổ sung thêm ít nhất 1 lối thoát nạn phù hợp.",
                citation: {
                  regulation_id: "11111111-1111-1111-1111-111111111111",
                  regulation: "QCVN 06:2022/BXD",
                  section: "3.1",
                  excerpt: "phải có ít nhất 2 lối thoát nạn",
                  source_url: null,
                },
              },
              {
                status: "PASS",
                severity: "minor",
                category: "fire_safety",
                title: "Chiều rộng hành lang đạt yêu cầu",
                description: "Hành lang 1.6 m vượt yêu cầu tối thiểu 1.4 m.",
                resolution: null,
                citation: null,
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await fillParamsAndContinue(page);
    await page.getByRole("button", { name: /bắt đầu quét/i }).click();

    // ComplianceScore renders the pass% in the donut center; with 1 PASS
    // out of 2 total findings that's 50%.
    await expect(page.getByText("50%")).toBeVisible();

    // Both findings render with their titles + severity badges.
    await expect(page.getByText("Số lối thoát nạn dưới yêu cầu")).toBeVisible();
    await expect(page.getByText("Chiều rộng hành lang đạt yêu cầu")).toBeVisible();
    await expect(page.getByText("CRITICAL")).toBeVisible();

    // FAIL finding's resolution + grounded citation render.
    await expect(page.getByText("Bổ sung thêm ít nhất 1 lối thoát nạn phù hợp.")).toBeVisible();
    await expect(page.getByText("QCVN 06:2022/BXD")).toBeVisible();
    await expect(page.getByText(/§\s*3\.1/)).toBeVisible();
    await expect(page.getByText("phải có ít nhất 2 lối thoát nạn")).toBeVisible();

    // Network contract: the POST carried the project_id we typed and the
    // default residential project_type.
    expect(lastBody).toMatchObject({
      project_id: PROJECT_ID,
      parameters: expect.objectContaining({ project_type: "residential" }),
    });
  });

  test("renders the amber advisory when the scan returns zero findings", async ({ page }) => {
    await page.route("**/api/v1/codeguard/scan", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            check_id: "66666666-6666-6666-6666-666666666666",
            status: "completed",
            total: 0,
            pass_count: 0,
            warn_count: 0,
            fail_count: 0,
            findings: [],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await fillParamsAndContinue(page);
    await page.getByRole("button", { name: /bắt đầu quét/i }).click();

    // Amber advisory header — present in the empty-findings branch only.
    await expect(page.getByText("Không có vấn đề nào được nêu")).toBeVisible();
    // Body text steers the user toward the disambiguation question
    // (was the corpus seeded for these categories?).
    await expect(page.getByText(/đã được nạp vào CODEGUARD chưa/)).toBeVisible();
    // The donut still renders — total 0 just means an empty grey ring
    // with 0% in the centre.
    await expect(page.getByText("0%")).toBeVisible();
  });

  test("shows a red error banner when the scan mutation rejects", async ({ page }) => {
    await page.route("**/api/v1/codeguard/scan", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "bad_gateway", message: "Auto-scan failed" }],
        }),
      });
    });

    await fillParamsAndContinue(page);
    await page.getByRole("button", { name: /bắt đầu quét/i }).click();

    // Red error banner renders in the results step. Without our patch
    // the user was stuck on the review step with no feedback at all.
    await expect(page.getByText("Lỗi khi quét tuân thủ")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Auto-scan failed/)).toBeVisible();

    // The "Quét lại" reset button is still reachable so the user can
    // retry without reloading the page.
    await expect(page.getByRole("button", { name: /quét lại/i })).toBeVisible();
  });
});
