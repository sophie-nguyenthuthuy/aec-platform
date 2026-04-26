import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: SiteEye site visits page (`/siteeye/visits`).
 *
 * Strategy
 * --------
 * `useSelectedProject()` reads from `localStorage["siteeye.project_id"]`,
 * so we use `page.addInitScript` to seed a fake project before the React
 * tree mounts. Without that the page short-circuits to a "Select a
 * project first." message — itself worth covering as a separate test.
 */

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

// Match `apps/api/schemas/siteeye.py::SiteVisit` (and packages/ui/siteeye
// types.ts). VisitList renders visit_date + photo_count + weather +
// workers_count + ai_summary — NOT notes — so we seed those.
const seedVisits = [
  {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    project_id: PROJECT_ID,
    visit_date: "2026-04-22",
    location: null,
    reported_by: null,
    weather: "Sunny",
    workers_count: 14,
    notes: null,
    ai_summary: "Floor 3 formwork in progress, no safety incidents.",
    photo_count: 12,
    created_at: "2026-04-22T08:00:00Z",
  },
  {
    id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    project_id: PROJECT_ID,
    visit_date: "2026-04-15",
    location: null,
    reported_by: null,
    weather: "Cloudy",
    workers_count: 22,
    notes: null,
    ai_summary: "Foundation pour complete, formwork stripped on east wing.",
    photo_count: 25,
    created_at: "2026-04-15T08:00:00Z",
  },
];

test.describe("SiteEye / Visits", () => {
  test("shows 'Select a project first' when localStorage has no project", async ({ page }) => {
    // Clear in case a previous test left state.
    await page.addInitScript(() => {
      window.localStorage.removeItem("siteeye.project_id");
    });

    await page.goto("/siteeye/visits");
    await expect(page.getByText(/select a project first/i)).toBeVisible();
  });

  test("renders the visit list once a project is selected", async ({ page }) => {
    await page.addInitScript((projectId) => {
      window.localStorage.setItem("siteeye.project_id", projectId);
    }, PROJECT_ID);

    await page.route(
      "**/api/v1/siteeye/visits*",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: seedVisits,
            meta: { page: 1, per_page: 50, total: seedVisits.length },
            errors: null,
          }),
        });
      },
    );

    await page.goto("/siteeye/visits");

    await expect(
      page.getByRole("heading", { name: /^site visits$/i }),
    ).toBeVisible();

    // Both visits land in the list. VisitList shows the AI summary and
    // visit_date prominently — those are the most stable assertion targets.
    await expect(page.getByText(/Floor 3 formwork in progress/)).toBeVisible();
    await expect(page.getByText(/Foundation pour complete/)).toBeVisible();
    await expect(page.getByText("2026-04-22")).toBeVisible();
    await expect(page.getByText(/12 photos/)).toBeVisible();
  });

  test("'New visit' toggles the inline form", async ({ page }) => {
    await page.addInitScript((projectId) => {
      window.localStorage.setItem("siteeye.project_id", projectId);
    }, PROJECT_ID);

    await page.route(
      "**/api/v1/siteeye/visits*",
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

    await page.goto("/siteeye/visits");

    const toggle = page.getByRole("button", { name: /new visit/i });
    await toggle.click();

    // Once the form is up the toggle text flips to "Cancel".
    await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
  });
});
