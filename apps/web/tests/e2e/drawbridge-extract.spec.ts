import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge schedule/dimension/material extractor page.
 *
 * What's covered
 * --------------
 * 1. The drawing-picker is gated on `project_id` — empty until the user
 *    types one, then populated from `/documents?doc_type=drawing`.
 * 2. Submitting fires `POST /api/v1/drawbridge/extract` with the picked
 *    document_id + target + (optionally) `pages`.
 * 3. The result renders schedules + dimensions + materials sections from
 *    the response, with the right counts in each section header.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const DOC_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd";

const seedDoc = {
  id: DOC_ID,
  organization_id: ORG_ID,
  project_id: PROJECT_ID,
  document_set_id: null,
  file_id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
  doc_type: "drawing" as const,
  drawing_number: "S-301",
  title: "Level 3 slab plan",
  revision: "A",
  discipline: "structural" as const,
  scale: "1:50",
  processing_status: "ready" as const,
  extracted_data: {},
  thumbnail_url: null,
  created_at: "2026-04-15T00:00:00Z",
};

test.describe("Drawbridge / Extract", () => {
  test("submits document_id + target + pages and renders the result", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/documents*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [seedDoc],
          meta: { page: 1, per_page: 100, total: 1 },
          errors: null,
        }),
      });
    });

    let extractBody: unknown = null;
    const extractSeen = page.waitForRequest(
      (r) =>
        r.url().includes("/api/v1/drawbridge/extract") &&
        r.method() === "POST",
    );

    await page.route("**/api/v1/drawbridge/extract", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      extractBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            document_id: DOC_ID,
            schedules: [
              {
                name: "Column schedule",
                page: 2,
                columns: ["mark", "size", "rebar"],
                rows: [
                  { cells: { mark: "C1", size: "300x300", rebar: "8T16" } },
                  { cells: { mark: "C2", size: "400x400", rebar: "12T20" } },
                ],
              },
            ],
            dimensions: [
              { label: "Slab thickness", value_mm: 200, raw: "200mm", page: 1, bbox: null },
              { label: "Beam depth", value_mm: 600, raw: "600", page: 1, bbox: null },
            ],
            materials: [
              {
                code: "C30",
                description: "Concrete C30",
                quantity: 100,
                unit: "m3",
                page: 1,
              },
            ],
            title_block: { project: "Demo Tower", drawn_by: "TT" },
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/extract");

    // The form labels are <label><span>…</span><select/></label> — no
    // for/id link, so `getByLabel` doesn't find the control. Scope via
    // the visible label text and reach the sibling control.
    const drawingPicker = page
      .getByText(/^bản vẽ$/i)
      .locator("..")
      .locator("select");
    await expect(drawingPicker).toBeDisabled();

    await page.getByPlaceholder("project_id").fill(PROJECT_ID);
    await expect(drawingPicker).toBeEnabled();
    await drawingPicker.selectOption(DOC_ID);

    const targetPicker = page
      .getByText(/^mục tiêu$/i)
      .locator("..")
      .locator("select");
    await targetPicker.selectOption("schedule");

    await page.getByPlaceholder("Tất cả").fill("1,2");

    await page.getByRole("button", { name: /trích xuất/i }).click();

    // Network contract first
    const req = await extractSeen;
    expect(req.method()).toBe("POST");
    expect(extractBody).toMatchObject({
      document_id: DOC_ID,
      target: "schedule",
      pages: [1, 2],
    });

    // Result sections render with their counts in headers.
    await expect(page.getByText(/schedules \(1\)/i)).toBeVisible();
    await expect(page.getByText(/dimensions \(2\)/i)).toBeVisible();
    await expect(page.getByText(/materials \(1\)/i)).toBeVisible();

    // Title block reflects payload keys. Match the heading rather than
    // the bare text — the target dropdown also has a "Title block" <option>.
    await expect(
      page.getByRole("heading", { name: /title block/i }),
    ).toBeVisible();
    await expect(page.getByText("Demo Tower")).toBeVisible();

    // A specific row from the schedule
    await expect(page.getByText("8T16")).toBeVisible();

    // A specific row from materials
    await expect(page.getByText("Concrete C30")).toBeVisible();
  });

  test("shows the empty-state prompt before the user runs an extract", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/documents*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 100, total: 0 },
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/extract");
    await expect(
      page.getByText(/Chọn một bản vẽ và bấm "Trích xuất"/),
    ).toBeVisible();
  });
});
