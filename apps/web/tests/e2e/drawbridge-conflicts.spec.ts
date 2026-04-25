import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge conflict dashboard.
 *
 * What's covered
 * --------------
 * 1. The severity tile counts are derived from the conflict list —
 *    one critical + one major + zero minor, seeded via GET /conflicts.
 * 2. "Quét xung đột" button is disabled until a project_id is entered,
 *    then posts to /conflict-scan and surfaces the "phát hiện N xung đột"
 *    summary.
 * 3. Clicking "Đã xử lý" on an open conflict PATCHes /conflicts/{id}
 *    with `status=resolved`.
 *
 * `useConflicts` has `enabled: Boolean(filters.project_id)` — the query
 * does NOT fire until the user fills the project_id input, so every test
 * has to do that before asserting on list content.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

const OPEN_CRITICAL_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc";
const OPEN_MAJOR_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd";

const baseConflict = {
  organization_id: ORG_ID,
  project_id: PROJECT_ID,
  status: "open" as const,
  conflict_type: "dimension" as const,
  description: null as string | null,
  document_a_id: null,
  chunk_a_id: null,
  document_b_id: null,
  chunk_b_id: null,
  ai_explanation: null,
  resolution_notes: null,
  detected_at: "2026-04-20T00:00:00Z",
  resolved_at: null,
  resolved_by: null,
  document_a: null,
  document_b: null,
};

const seedConflicts = [
  {
    ...baseConflict,
    id: OPEN_CRITICAL_ID,
    severity: "critical" as const,
    description: "Slab thickness mismatch: A-101 says 200mm, S-301 says 180mm",
  },
  {
    ...baseConflict,
    id: OPEN_MAJOR_ID,
    severity: "major" as const,
    description: "Column grid offset between architectural and structural",
  },
];

test.describe("Drawbridge / Conflicts", () => {
  test("renders severity tiles and conflict cards from the list endpoint", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/conflicts*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: seedConflicts,
          meta: { page: 1, per_page: 50, total: seedConflicts.length },
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/conflicts");

    // Enter a project_id — this is what flips `enabled` on useConflicts.
    await page.getByPlaceholder("project_id").fill(PROJECT_ID);

    // Both conflict descriptions render once the list resolves.
    await expect(page.getByText(/Slab thickness mismatch/)).toBeVisible();
    await expect(
      page.getByText(/Column grid offset between architectural and structural/),
    ).toBeVisible();

    // Severity tiles render the derived counts. Scope the lookup to the
    // `<section class="grid grid-cols-3">` — the word "Nghiêm trọng" also
    // appears on each critical conflict card further down the page, so
    // searching globally hits a strict-mode violation.
    const tiles = page.locator("section.grid.grid-cols-3 > div");
    await expect(tiles.nth(0)).toContainText(/nghiêm trọng/i);
    await expect(tiles.nth(0)).toContainText("1");
    await expect(tiles.nth(1)).toContainText("Lớn");
    await expect(tiles.nth(1)).toContainText("1");
    await expect(tiles.nth(2)).toContainText("Nhỏ");
    await expect(tiles.nth(2)).toContainText("0");
  });

  test("Quét xung đột posts to /conflict-scan and shows the summary", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/conflicts*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 50, total: 0 },
          errors: null,
        }),
      });
    });

    let scanBody: unknown = null;
    const scanSeen = page.waitForRequest(
      (r) =>
        r.url().includes("/api/v1/drawbridge/conflict-scan") &&
        r.method() === "POST",
    );

    await page.route("**/api/v1/drawbridge/conflict-scan", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      scanBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            project_id: PROJECT_ID,
            scanned_documents: 12,
            candidates_evaluated: 34,
            conflicts_found: 3,
            conflicts: [],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/conflicts");

    // Button is disabled without a project_id.
    const scanButton = page.getByRole("button", { name: /quét xung đột/i });
    await expect(scanButton).toBeDisabled();

    await page.getByPlaceholder("project_id").fill(PROJECT_ID);
    await expect(scanButton).toBeEnabled();

    await scanButton.click();

    const scanReq = await scanSeen;
    expect(scanReq.method()).toBe("POST");
    expect(scanBody).toMatchObject({ project_id: PROJECT_ID });

    // Summary banner after the scan lands.
    await expect(page.getByText(/12 tài liệu/)).toBeVisible();
    await expect(page.getByText(/34 cặp/)).toBeVisible();
    await expect(page.getByText(/3 xung đột/)).toBeVisible();
  });

  test("'Đã xử lý' PATCHes the conflict to resolved", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/conflicts*", async (route: Route) => {
      // Only intercept the list (trailing ?query…), not the PATCH to /{id}.
      const url = route.request().url();
      if (route.request().method() === "GET" && url.match(/\/conflicts\?/)) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: seedConflicts,
            meta: { page: 1, per_page: 50, total: seedConflicts.length },
            errors: null,
          }),
        });
        return;
      }
      return route.fallback();
    });

    let patchBody: unknown = null;
    const patchSeen = page.waitForRequest(
      (r) =>
        r.url().includes(`/api/v1/drawbridge/conflicts/${OPEN_CRITICAL_ID}`) &&
        r.method() === "PATCH",
    );

    await page.route(
      `**/api/v1/drawbridge/conflicts/${OPEN_CRITICAL_ID}`,
      async (route: Route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        patchBody = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              ...seedConflicts[0],
              status: "resolved",
              resolved_at: "2026-04-23T08:00:00Z",
            },
            meta: null,
            errors: null,
          }),
        });
      },
    );

    await page.goto("/drawbridge/conflicts");
    await page.getByPlaceholder("project_id").fill(PROJECT_ID);

    // Scope to the critical card, click its "Đã xử lý" button.
    const criticalCard = page
      .locator("article")
      .filter({ hasText: /Slab thickness mismatch/ });
    await expect(criticalCard).toBeVisible();
    await criticalCard.getByRole("button", { name: /đã xử lý/i }).click();

    const patchReq = await patchSeen;
    expect(patchReq.method()).toBe("PATCH");
    expect(patchBody).toMatchObject({ status: "resolved" });
  });
});
