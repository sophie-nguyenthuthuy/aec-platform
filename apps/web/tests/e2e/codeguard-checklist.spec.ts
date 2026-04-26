import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD permit checklist page.
 *
 * What's covered
 * --------------
 * 1. Generate flow — fill params, click "Tạo checklist", see the items
 *    rendered with title / required badge / regulation_ref / description.
 *    POST body matches input.
 * 2. Mark-item flow — checking the checkbox on an item fires a
 *    POST /checks/{id}/mark-item with `status: "done"`. The progress
 *    counter and percent reflect the server's returned state.
 * 3. Empty-items advisory — when the LLM returns `items: []`, the page
 *    shows the amber "Checklist trống" Info card. Mirror of the scan
 *    page's empty-findings treatment.
 * 4. Error path on generate — backend 502 surfaces a red banner above
 *    the form (form stays filled so user can retry without re-typing).
 * 5. Error path on mark-item — when the mark mutation rejects, the
 *    in-list red "Không lưu được trạng thái" banner appears and is
 *    dismissable. Items stay reachable.
 */

const PROJECT_ID = "77777777-7777-7777-7777-777777777777";

async function fillFormAndGenerate(page: Page) {
  await page.goto("/codeguard/checklist");
  await page.locator('input').first().fill(PROJECT_ID);
  // Jurisdiction defaults to "Hồ Chí Minh", project_type to residential.
  await page.getByRole("button", { name: /tạo checklist/i }).click();
}

test.describe("CODEGUARD / Checklist", () => {
  test("generates a checklist and renders items with required badges + regulation refs", async ({ page }) => {
    let lastBody: unknown = null;

    await page.route("**/api/v1/codeguard/permit-checklist", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: "88888888-8888-8888-8888-888888888888",
            project_id: PROJECT_ID,
            jurisdiction: "Hồ Chí Minh",
            project_type: "residential",
            generated_at: "2026-04-26T00:00:00Z",
            completed_at: null,
            items: [
              {
                id: "site-survey",
                title: "Khảo sát hiện trạng",
                description: "Bản vẽ khảo sát địa hình và địa chất.",
                regulation_ref: "QCVN 06:2022 §1.1",
                required: true,
                status: "pending",
              },
              {
                id: "fire-approval",
                title: "Phê duyệt PCCC",
                description: null,
                regulation_ref: null,
                required: false,
                status: "pending",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await fillFormAndGenerate(page);

    // Header renders jurisdiction + project_type and a 0/2 progress.
    await expect(page.getByText(/Hồ Chí Minh.*residential/)).toBeVisible();
    await expect(page.getByText("0/2")).toBeVisible();
    await expect(page.getByText("0% hoàn thành")).toBeVisible();

    // Both items render with their titles.
    await expect(page.getByText("Khảo sát hiện trạng")).toBeVisible();
    await expect(page.getByText("Phê duyệt PCCC")).toBeVisible();

    // First item has the "Bắt buộc" required badge + the regulation ref chip.
    await expect(page.getByText("Bắt buộc")).toBeVisible();
    await expect(page.getByText("QCVN 06:2022 §1.1")).toBeVisible();

    // POST body carries what the user filled in.
    expect(lastBody).toMatchObject({
      project_id: PROJECT_ID,
      jurisdiction: "Hồ Chí Minh",
      project_type: "residential",
    });
  });

  test("marks an item as done and updates the progress counter", async ({ page }) => {
    const checklistId = "99999999-9999-9999-9999-999999999999";

    // Generate response.
    await page.route("**/api/v1/codeguard/permit-checklist", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: checklistId,
            project_id: PROJECT_ID,
            jurisdiction: "Hồ Chí Minh",
            project_type: "residential",
            generated_at: "2026-04-26T00:00:00Z",
            completed_at: null,
            items: [
              {
                id: "site-survey",
                title: "Khảo sát hiện trạng",
                description: null,
                regulation_ref: null,
                required: true,
                status: "pending",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    let markBody: unknown = null;
    // Mark-item response — returns the same checklist with the item flipped to done.
    await page.route(`**/api/v1/codeguard/checks/${checklistId}/mark-item`, async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      markBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: checklistId,
            project_id: PROJECT_ID,
            jurisdiction: "Hồ Chí Minh",
            project_type: "residential",
            generated_at: "2026-04-26T00:00:00Z",
            completed_at: null,
            items: [
              {
                id: "site-survey",
                title: "Khảo sát hiện trạng",
                description: null,
                regulation_ref: null,
                required: true,
                status: "done",
                updated_at: "2026-04-26T00:01:00Z",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await fillFormAndGenerate(page);
    await expect(page.getByText("0/1")).toBeVisible();

    // Click the checkbox — fires the mark-item mutation.
    await page.getByRole("checkbox").click();

    // Counter rebinds to the server's returned state.
    await expect(page.getByText("1/1")).toBeVisible();
    await expect(page.getByText("100% hoàn thành")).toBeVisible();

    // Network contract: mark-item POST carried the right item_id + status.
    expect(markBody).toMatchObject({ item_id: "site-survey", status: "done" });
  });

  test("renders the amber advisory when the LLM returns zero items", async ({ page }) => {
    await page.route("**/api/v1/codeguard/permit-checklist", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            project_id: PROJECT_ID,
            jurisdiction: "Hồ Chí Minh",
            project_type: "residential",
            generated_at: "2026-04-26T00:00:00Z",
            completed_at: null,
            items: [],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await fillFormAndGenerate(page);

    // The amber Info card replaces the (empty) items list.
    await expect(page.getByText("Checklist trống")).toBeVisible();
    await expect(page.getByText(/chưa sinh được mục nào/)).toBeVisible();
    // Counter still shows 0/0.
    await expect(page.getByText("0/0")).toBeVisible();
    // Reset button is still reachable.
    await expect(page.getByRole("button", { name: /tạo lại/i })).toBeVisible();
  });

  test("shows a red error banner when generate fails (form stays filled)", async ({ page }) => {
    await page.route("**/api/v1/codeguard/permit-checklist", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "bad_gateway", message: "Checklist generation failed" }],
        }),
      });
    });

    await fillFormAndGenerate(page);

    // Red banner above the form. The form itself is still rendered so
    // the user can retry without losing their inputs.
    await expect(page.getByText("Lỗi khi tạo checklist")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Checklist generation failed/)).toBeVisible();

    // The "Tạo checklist" button should still be there and clickable
    // (form stayed mounted).
    await expect(page.getByRole("button", { name: /tạo checklist/i })).toBeEnabled();
  });

  test("shows a dismissable inline error when mark-item fails", async ({ page }) => {
    const checklistId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

    await page.route("**/api/v1/codeguard/permit-checklist", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: checklistId,
            project_id: PROJECT_ID,
            jurisdiction: "Hồ Chí Minh",
            project_type: "residential",
            generated_at: "2026-04-26T00:00:00Z",
            completed_at: null,
            items: [
              {
                id: "site-survey",
                title: "Khảo sát hiện trạng",
                description: null,
                regulation_ref: null,
                required: true,
                status: "pending",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.route(`**/api/v1/codeguard/checks/${checklistId}/mark-item`, async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "bad_gateway", message: "Could not persist status" }],
        }),
      });
    });

    await fillFormAndGenerate(page);
    await page.getByRole("checkbox").click();

    // Inline banner appears with the failure message.
    await expect(page.getByText("Không lưu được trạng thái")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Could not persist status/)).toBeVisible();

    // Dismiss button removes the banner without reloading.
    await page.getByRole("button", { name: /^đóng$/i }).click();
    await expect(page.getByText("Không lưu được trạng thái")).toHaveCount(0);
  });
});
