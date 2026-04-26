import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: BidRadar tenders list (`/bidradar/tenders`).
 *
 * What's covered
 * --------------
 * 1. Table render — `GET /api/v1/bidradar/tenders` returns scraped
 *    opportunities; rows show title, issuer, province, budget, deadline.
 * 2. Filter inputs (search / province / discipline) re-fire the GET
 *    with the typed values in the query string.
 * 3. Empty-state copy.
 */

const seedTenders = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    title: "District 2 metro line extension — civil works",
    issuer: "HCMC PMU",
    province: "HCMC",
    discipline: "civil",
    budget_vnd: 450_000_000_000,
    submission_deadline: "2026-06-15T00:00:00Z",
    source: "muasamcong",
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    title: "Hanoi school district — MEP retrofit",
    issuer: "Hanoi DOET",
    province: "Hanoi",
    discipline: "mep",
    budget_vnd: 22_000_000_000,
    submission_deadline: "2026-05-20T00:00:00Z",
    source: "dauthau.info",
  },
];

test.describe("BidRadar / Tenders", () => {
  test("renders the tender table from the list endpoint", async ({ page }) => {
    await page.route(
      "**/api/v1/bidradar/tenders*",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: seedTenders,
            meta: { page: 1, per_page: 50, total: seedTenders.length },
            errors: null,
          }),
        });
      },
    );

    await page.goto("/bidradar/tenders");

    await expect(
      page.getByRole("heading", { name: /all scraped tenders/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", {
        name: /District 2 metro line extension — civil works/,
      }),
    ).toBeVisible();
    await expect(page.getByText("HCMC PMU")).toBeVisible();
    await expect(page.getByText("muasamcong")).toBeVisible();
  });

  test("filter inputs feed back into the GET query string", async ({ page }) => {
    const seen: string[] = [];

    await page.route(
      "**/api/v1/bidradar/tenders*",
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

    await page.goto("/bidradar/tenders");

    await page.getByPlaceholder(/Search title, issuer/i).fill("metro");
    await page.getByPlaceholder("Province").fill("HCMC");
    await page.getByPlaceholder("Discipline").fill("civil");

    await expect
      .poll(() => seen.some((q) => q.includes("q=metro")), { timeout: 3000 })
      .toBe(true);
    await expect
      .poll(() => seen.some((q) => q.includes("province=HCMC")), { timeout: 3000 })
      .toBe(true);
    await expect
      .poll(() => seen.some((q) => q.includes("discipline=civil")), { timeout: 3000 })
      .toBe(true);
  });

  test("shows empty-state when no tenders match", async ({ page }) => {
    await page.route(
      "**/api/v1/bidradar/tenders*",
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

    await page.goto("/bidradar/tenders");
    await expect(page.getByText(/no tenders match your filters/i)).toBeVisible();
  });
});
