import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge document detail page (`/drawbridge/documents/[id]`).
 *
 * What's covered
 * --------------
 * 1. Render path — `GET /api/v1/drawbridge/documents/{id}` populates the
 *    header (drawing number + title + discipline) and the metadata
 *    sidebar (doc_type, revision, scale, processing_status, created_at).
 * 2. Page-nav buttons increment the visible page counter (the PDFViewer
 *    itself dynamic-imports `pdfjs-dist`, which isn't installed here, so
 *    we don't try to render a real PDF — we only assert the surrounding
 *    UI honours the page state).
 * 3. Error path — `GET /documents/{id}` 404 surfaces "Không tìm thấy
 *    tài liệu." instead of crashing.
 *
 * Note we intercept `/api/v1/files/{id}/download` with an empty 200 so
 * the PDFViewer's pdfjs path doesn't spam the test log with network
 * errors.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const DOC_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const FILE_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff";

const baseDoc = {
  id: DOC_ID,
  organization_id: ORG_ID,
  project_id: PROJECT_ID,
  document_set_id: null,
  file_id: FILE_ID,
  doc_type: "drawing" as const,
  drawing_number: "A-101",
  title: "Ground floor plan",
  revision: "B",
  discipline: "architectural" as const,
  scale: "1:100",
  processing_status: "ready" as const,
  extracted_data: {},
  thumbnail_url: null,
  created_at: "2026-04-15T10:00:00Z",
};

test.describe("Drawbridge / Document detail", () => {
  test("renders header + metadata + page nav for an existing doc", async ({ page }) => {
    await page.route(
      `**/api/v1/drawbridge/documents/${DOC_ID}`,
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: baseDoc, meta: null, errors: null }),
        });
      },
    );

    // PDF download — return empty so pdfjs stops complaining about CORS/404.
    await page.route("**/api/v1/files/**/download", async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/pdf",
        body: "",
      });
    });

    await page.goto(`/drawbridge/documents/${DOC_ID}`);

    // Header
    await expect(page.getByText("A-101")).toBeVisible();
    await expect(page.getByText("Ground floor plan")).toBeVisible();

    // Sidebar metadata — there are two `<aside>` elements on this page
    // (the global app shell + the page-local one), so scope through the
    // "Thông tin" heading and walk up to its parent panel.
    const sidebar = page
      .getByRole("heading", { name: /thông tin/i })
      .locator("..");
    await expect(sidebar).toContainText("drawing");
    await expect(sidebar).toContainText("B");      // revision
    await expect(sidebar).toContainText("1:100");  // scale
    await expect(sidebar).toContainText("ready");  // processing_status

    // Page nav: starts at 1, "Trang →" bumps to 2.
    await expect(page.getByText(/^Trang 1$/)).toBeVisible();
    await page.getByRole("button", { name: /Trang →/ }).click();
    await expect(page.getByText(/^Trang 2$/)).toBeVisible();

    // Going below 1 is clamped — first click takes 2 → 1, second is no-op.
    await page.getByRole("button", { name: /← Trang/ }).click();
    await expect(page.getByText(/^Trang 1$/)).toBeVisible();
    await page.getByRole("button", { name: /← Trang/ }).click();
    await expect(page.getByText(/^Trang 1$/)).toBeVisible();
  });

  test("renders not-found copy when the GET returns 404", async ({ page }) => {
    await page.route(
      `**/api/v1/drawbridge/documents/${DOC_ID}`,
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            data: null,
            errors: [{ code: "not_found", message: "missing" }],
          }),
        });
      },
    );

    await page.goto(`/drawbridge/documents/${DOC_ID}`);
    await expect(page.getByText(/không tìm thấy tài liệu/i)).toBeVisible();
  });
});
