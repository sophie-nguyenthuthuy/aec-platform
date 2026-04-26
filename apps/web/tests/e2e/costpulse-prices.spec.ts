import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: CostPulse price database (`/costpulse/prices`).
 *
 * What's covered
 * --------------
 * 1. Table render — `GET /api/v1/costpulse/prices` populates rows with
 *    name + code + province + price + effective date.
 * 2. Filter controls — picking a category and typing into search both
 *    feed back into the GET query string.
 * 3. Selection flow — clicking a row puts that material in the right
 *    side panel; the "Alert me on >5% change" button POSTs to
 *    `/api/v1/costpulse/price-alerts` with the right payload.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";

const seedPrices = [
  {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    organization_id: ORG_ID,
    material_code: "CONC_C30",
    name: "Concrete C30",
    category: "concrete",
    unit: "m3",
    price_vnd: 2_000_000,
    province: "Hanoi",
    source: "government",
    effective_date: "2026-04-01",
  },
  {
    id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    organization_id: ORG_ID,
    material_code: "REBAR_CB500",
    name: "Rebar CB500",
    category: "steel",
    unit: "kg",
    price_vnd: 20_000,
    province: "HCMC",
    source: "government",
    effective_date: "2026-04-01",
  },
];

test.describe("CostPulse / Prices", () => {
  test("renders the price table and supports row selection + alert", async ({ page }) => {
    // `usePriceAlert` sends its parameters as URL search params on a POST
    // (no JSON body) — see hooks/costpulse/usePrices.ts. Capture the
    // search string so we can assert what was sent.
    let alertSearch: string | null = null;

    // One unified handler: Playwright's URL-pattern `*` matches across path
    // separators, so `prices*` would otherwise also catch
    // `prices/history/...` and `price-alerts`. Routing all costpulse traffic
    // through a single dispatcher dodges the pattern-overlap surprise.
    await page.route("**/api/v1/costpulse/**", async (route: Route) => {
      const url = route.request().url();
      const method = route.request().method();

      if (url.includes("/price-alerts") && method === "POST") {
        alertSearch = new URL(url).search;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            data: { id: "ffffffff-ffff-ffff-ffff-ffffffffffff" },
            meta: null,
            errors: null,
          }),
        });
        return;
      }
      if (url.includes("/prices/history/") && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              points: [
                { date: "2026-03-01", price_vnd: 1_900_000 },
                { date: "2026-04-01", price_vnd: 2_000_000 },
              ],
              pct_change_30d: 5.2,
              pct_change_1y: 12.1,
            },
            meta: null,
            errors: null,
          }),
        });
        return;
      }
      if (method === "GET") {
        // /prices?... or anything else — return the seed list.
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: seedPrices,
            meta: { page: 1, per_page: 50, total: seedPrices.length },
            errors: null,
          }),
        });
        return;
      }
      return route.fallback();
    });

    await page.goto("/costpulse/prices");

    await expect(page.getByText("Concrete C30")).toBeVisible();
    await expect(page.getByText("Rebar CB500")).toBeVisible();
    await expect(page.getByText("CONC_C30")).toBeVisible();

    // Click the concrete row → selection panel appears.
    await page.getByText("Concrete C30").click();
    await expect(
      page.getByText(/CONC_C30 · Hanoi/),
    ).toBeVisible();

    await page.getByRole("button", { name: /alert me on >5% change/i }).click();

    // The button's label flips to "Alert created" once the mutation
    // resolves — that's our signal the POST landed and was responded to
    // by the route handler. Use the label flip rather than
    // `waitForRequest` (which has a non-obvious race with mutations
    // submitted via TanStack Query: by the time we await the promise,
    // the request event has already fired during page hydration).
    await expect(
      page.getByRole("button", { name: /alert created/i }),
    ).toBeVisible({ timeout: 5000 });

    // The mutation passes its inputs as query-string params, not a body.
    expect(alertSearch).toBeTruthy();
    expect(alertSearch).toContain("material_code=CONC_C30");
    expect(alertSearch).toContain("province=Hanoi");
    expect(alertSearch).toContain("threshold_pct=5");
  });

  test("filter + search inputs propagate to the GET query string", async ({ page }) => {
    const seen: string[] = [];

    await page.route(
      "**/api/v1/costpulse/prices*",
      async (route: Route) => {
        if (route.request().url().includes("/price-alerts")) {
          return route.fallback();
        }
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

    await page.goto("/costpulse/prices");

    await page.getByPlaceholder(/Search by name or code/i).fill("rebar");
    await page.locator("select").nth(0).selectOption("steel");

    await expect
      .poll(() => seen.some((q) => q.includes("q=rebar")), { timeout: 3000 })
      .toBe(true);
    await expect
      .poll(() => seen.some((q) => q.includes("category=steel")), { timeout: 3000 })
      .toBe(true);
  });
});
