import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: WinWork proposals list (`/winwork`).
 *
 * What's covered
 * --------------
 * 1. List render — `GET /api/v1/winwork/proposals` returns a couple
 *    proposals; cards render with title + client name visible.
 * 2. Status filter pills mutate the GET query string. Clicking "won"
 *    re-fires the request with `status=won`.
 * 3. Empty-state copy renders the "No proposals yet." card.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";

const baseProposal = {
  organization_id: ORG_ID,
  status: "draft" as const,
  fee_total_vnd: 1_500_000_000,
  area_sqm: 1200,
  margin_pct: 18,
  win_probability: 0.55,
  template_id: null as string | null,
  expires_at: "2026-06-01T00:00:00Z",
  created_at: "2026-04-15T00:00:00Z",
  updated_at: "2026-04-15T00:00:00Z",
};

const seedProposals = [
  {
    ...baseProposal,
    id: "11111111-1111-1111-1111-111111111111",
    title: "Marina Tower podium fit-out",
    client_name: "Marina Holdings JSC",
    project_type: "residential",
    status: "draft" as const,
  },
  {
    ...baseProposal,
    id: "22222222-2222-2222-2222-222222222222",
    title: "District 7 hospital interior",
    client_name: "Saigon Health Group",
    project_type: "healthcare",
    status: "won" as const,
    win_probability: 1,
  },
];

test.describe("WinWork / Proposals", () => {
  test("renders proposal cards from the list endpoint", async ({ page }) => {
    await page.route(
      "**/api/v1/winwork/proposals*",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: seedProposals,
            meta: { page: 1, per_page: 50, total: seedProposals.length },
            errors: null,
          }),
        });
      },
    );

    await page.goto("/winwork");

    await expect(
      page.getByRole("heading", { name: /^proposals$/i }),
    ).toBeVisible();
    await expect(page.getByText("Marina Tower podium fit-out")).toBeVisible();
    await expect(page.getByText("District 7 hospital interior")).toBeVisible();
    await expect(page.getByText("Marina Holdings JSC")).toBeVisible();
  });

  test("status filter pills carry through to the GET query string", async ({ page }) => {
    const seen: string[] = [];

    await page.route(
      "**/api/v1/winwork/proposals*",
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

    await page.goto("/winwork");

    // Initial fire — no status filter (the "all" pill is selected).
    await expect.poll(() => seen.length, { timeout: 3000 }).toBeGreaterThan(0);

    // Click "won" filter
    await page.getByRole("button", { name: /^won$/ }).click();

    await expect
      .poll(() => seen.some((q) => q.includes("status=won")), { timeout: 3000 })
      .toBe(true);
  });

  test("shows empty-state when there are no proposals", async ({ page }) => {
    await page.route(
      "**/api/v1/winwork/proposals*",
      async (route: Route) => {
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

    await page.goto("/winwork");
    await expect(page.getByText(/no proposals yet/i)).toBeVisible();
  });
});
