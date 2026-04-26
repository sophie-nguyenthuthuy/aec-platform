import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Handover packages list (`/handover`).
 *
 * What's covered
 * --------------
 * 1. List render — `GET /api/v1/handover/packages` returns packages,
 *    each `PackageCard` shows the name + status.
 * 2. Status filter pills carry through to the GET query string.
 * 3. "Tạo gói mới" opens the create dialog and POSTs the typed payload
 *    to `/api/v1/handover/packages`.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

const seedPackages = [
  {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    organization_id: ORG_ID,
    project_id: PROJECT_ID,
    name: "Bàn giao giai đoạn 1",
    status: "in_review" as const,
    description: null,
    created_at: "2026-04-15T08:00:00Z",
    updated_at: "2026-04-15T08:00:00Z",
    closeout_progress: { total: 12, completed: 8 },
  },
  {
    id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    organization_id: ORG_ID,
    project_id: PROJECT_ID,
    name: "Bàn giao toàn dự án",
    status: "draft" as const,
    description: null,
    created_at: "2026-04-10T08:00:00Z",
    updated_at: "2026-04-10T08:00:00Z",
    closeout_progress: { total: 24, completed: 0 },
  },
];

test.describe("Handover / Packages", () => {
  test("renders the package grid from the list endpoint", async ({ page }) => {
    await page.route(
      "**/api/v1/handover/packages*",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: seedPackages,
            meta: { page: 1, per_page: 50, total: seedPackages.length },
            errors: null,
          }),
        });
      },
    );

    await page.goto("/handover");

    await expect(
      page.getByRole("heading", { name: /gói bàn giao/i }),
    ).toBeVisible();
    await expect(page.getByText("Bàn giao giai đoạn 1")).toBeVisible();
    await expect(page.getByText("Bàn giao toàn dự án")).toBeVisible();
  });

  test("status filter pills propagate to the GET query string", async ({ page }) => {
    const seen: string[] = [];

    await page.route(
      "**/api/v1/handover/packages*",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        seen.push(new URL(route.request().url()).search);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: [],
            meta: { page: 1, per_page: 50, total: 0 },
            errors: null,
          }),
        });
      },
    );

    await page.goto("/handover");

    // "Đã duyệt" maps to status=approved.
    await page.getByRole("button", { name: /^đã duyệt$/i }).click();

    await expect
      .poll(() => seen.some((q) => q.includes("status=approved")), {
        timeout: 3000,
      })
      .toBe(true);
  });

  test("create dialog POSTs the typed payload", async ({ page }) => {
    await page.route(
      "**/api/v1/handover/packages*",
      async (route: Route) => {
        // GET handled here; POST handled in the next route.
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
      },
    );

    let createBody: unknown = null;
    const createSeen = page.waitForRequest(
      (r) =>
        r.url().endsWith("/api/v1/handover/packages") &&
        r.method() === "POST",
    );

    await page.route(
      "**/api/v1/handover/packages",
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        createBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              ...seedPackages[0],
              id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
              name: "Bàn giao mới",
            },
            meta: null,
            errors: null,
          }),
        });
      },
    );

    await page.goto("/handover");

    await page.getByRole("button", { name: /tạo gói mới/i }).click();

    await page.getByRole("textbox").nth(0).fill(PROJECT_ID); // first textbox = project_id
    await page.getByPlaceholder("Bàn giao giai đoạn 1").fill("Bàn giao mới");

    await page.getByRole("button", { name: /^tạo$/i }).click();

    const req = await createSeen;
    expect(req.method()).toBe("POST");
    expect(createBody).toMatchObject({
      project_id: PROJECT_ID,
      name: "Bàn giao mới",
      auto_populate: true, // default checkbox state
    });
  });
});
