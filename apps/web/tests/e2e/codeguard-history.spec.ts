import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD compliance history (audit trail).
 *
 * What's covered
 * --------------
 * 1. Empty hint — landing on the page with no project_id submitted shows
 *    the dashed "nhập mã dự án" hint, NOT a list of zero items.
 * 2. List render — searching by project_id loads checks and renders one
 *    card per row with type-specific summaries:
 *      * manual_query → question + answer (truncated) + citation count
 *      * auto_scan    → PASS/WARN/FAIL count chips + categories list
 * 3. No-checks advisory — when the API returns `data: []` for a real
 *    project_id, the amber "Chưa có kiểm tra nào" Info card renders.
 *    Mirrors the abstain/empty patterns from the other surfaces.
 * 4. Type filter — selecting "Quét tuân thủ" sets `check_type=auto_scan`
 *    on the GET request URL.
 * 5. Error path — when the API returns 500, the red "Lỗi khi tải lịch
 *    sử" banner renders.
 */

const PROJECT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc";

test.describe("CODEGUARD / History", () => {
  test("shows the empty hint before any project_id is submitted", async ({ page }) => {
    await page.goto("/codeguard/history");
    await expect(page.getByText("Nhập mã dự án để xem lịch sử kiểm tra.")).toBeVisible();

    // The "Tra cứu" search button is disabled until something is typed.
    const search = page.getByRole("button", { name: /tra cứu/i });
    await expect(search).toBeDisabled();
  });

  test("lists checks with type-specific summaries (query + scan)", async ({ page }) => {
    await page.route(`**/api/v1/codeguard/checks/${PROJECT_ID}*`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [
            {
              id: "11111111-1111-1111-1111-111111111111",
              project_id: PROJECT_ID,
              check_type: "manual_query",
              status: "completed",
              input: { question: "Chiều rộng hành lang thoát nạn?" },
              // Note: query route persists a single dict (not a list) as
              // findings — the page's QuerySummary handles that shape.
              findings: {
                answer: "Hành lang thoát nạn phải có chiều rộng tối thiểu 1.4 m.",
                confidence: 0.88,
                citations: [
                  { regulation: "QCVN 06:2022/BXD", section: "3.2.1", excerpt: "..." },
                ],
                related_questions: [],
              } as unknown as unknown[],
              regulations_referenced: ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
              created_by: "user-1",
              created_at: "2026-04-26T10:00:00Z",
            },
            {
              id: "22222222-2222-2222-2222-222222222222",
              project_id: PROJECT_ID,
              check_type: "auto_scan",
              status: "completed",
              input: { parameters: { project_type: "residential", floors_above: 6 } },
              findings: [
                { status: "FAIL", severity: "critical", category: "fire_safety", title: "x", description: "y" },
                { status: "PASS", severity: "minor", category: "fire_safety", title: "z", description: "w" },
                { status: "WARN", severity: "major", category: "accessibility", title: "a", description: "b" },
              ],
              regulations_referenced: [],
              created_by: "user-1",
              created_at: "2026-04-25T15:30:00Z",
            },
          ],
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/history");
    await page.locator('input[type="text"]').first().fill(PROJECT_ID);
    await page.getByRole("button", { name: /tra cứu/i }).click();

    // Query summary renders question + answer + citation count.
    await expect(page.getByText("Câu hỏi")).toBeVisible();
    await expect(page.getByText("Chiều rộng hành lang thoát nạn?")).toBeVisible();
    await expect(page.getByText(/Hành lang thoát nạn phải có chiều rộng/)).toBeVisible();
    await expect(page.getByText("1 trích dẫn")).toBeVisible();
    await expect(page.getByText(/Độ tin cậy:\s*88%/)).toBeVisible();

    // Scan summary renders the three count chips with the right values.
    // 1 PASS, 1 WARN, 1 FAIL.
    await expect(page.getByText(/Đạt:\s*1/)).toBeVisible();
    await expect(page.getByText(/Cảnh báo:\s*1/)).toBeVisible();
    await expect(page.getByText(/Vi phạm:\s*1/)).toBeVisible();
    // Categories surfaced from the findings.
    await expect(page.getByText(/Hạng mục:.*fire_safety.*accessibility/)).toBeVisible();

    // Type badges — one "Hỏi", one "Quét".
    await expect(page.getByText(/^Hỏi$/)).toBeVisible();
    await expect(page.getByText(/^Quét$/)).toBeVisible();
  });

  test("renders the amber advisory when the project has no checks", async ({ page }) => {
    await page.route(`**/api/v1/codeguard/checks/${PROJECT_ID}*`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [], meta: null, errors: null }),
      });
    });

    await page.goto("/codeguard/history");
    await page.locator('input[type="text"]').first().fill(PROJECT_ID);
    await page.getByRole("button", { name: /tra cứu/i }).click();

    await expect(page.getByText("Chưa có kiểm tra nào")).toBeVisible();
    // The advisory body steers the user toward Hỏi / Quét tuân thủ as
    // ways to populate the audit trail.
    await expect(page.getByText(/Hãy thử "Hỏi quy chuẩn"/)).toBeVisible();
  });

  test("type filter forwards check_type=auto_scan to the API", async ({ page }) => {
    const requestUrls: string[] = [];

    await page.route(`**/api/v1/codeguard/checks/${PROJECT_ID}*`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      requestUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [], meta: null, errors: null }),
      });
    });

    await page.goto("/codeguard/history");
    // Pick the auto_scan filter BEFORE submitting, so the first GET
    // already carries `check_type=auto_scan`.
    await page.locator("select").selectOption("auto_scan");
    await page.locator('input[type="text"]').first().fill(PROJECT_ID);
    await page.getByRole("button", { name: /tra cứu/i }).click();

    // Wait for the empty-state advisory to confirm the GET resolved.
    await expect(page.getByText("Chưa có kiểm tra nào")).toBeVisible();

    expect(requestUrls.length).toBeGreaterThanOrEqual(1);
    expect(requestUrls.at(-1)).toContain("check_type=auto_scan");
  });

  test("shows a red error banner when the API returns 500", async ({ page }) => {
    await page.route(`**/api/v1/codeguard/checks/${PROJECT_ID}*`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "internal", message: "DB unreachable" }],
        }),
      });
    });

    await page.goto("/codeguard/history");
    await page.locator('input[type="text"]').first().fill(PROJECT_ID);
    await page.getByRole("button", { name: /tra cứu/i }).click();

    await expect(page.getByText("Lỗi khi tải lịch sử")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/DB unreachable/)).toBeVisible();
  });
});
