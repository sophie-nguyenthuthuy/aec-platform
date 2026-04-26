import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge conflict detail page (`/drawbridge/conflicts/[id]`).
 *
 * What's covered
 * --------------
 * 1. Render path — `GET /api/v1/drawbridge/conflicts/{id}` populates the
 *    severity/status/type pills, the AI explanation banner, and both
 *    document-A / document-B excerpt panes.
 * 2. "Tạo RFI" — `POST /rfis/generate` with `conflict_id`, then redirects
 *    to `/drawbridge/rfis`.
 * 3. "Đánh dấu đã xử lý" with notes filled in PATCHes to
 *    `/conflicts/{id}` with `{ status: "resolved", resolution_notes }`.
 *
 * The PDFViewer dynamic-imports `pdfjs-dist`, which isn't installed in
 * this workspace; we intercept the file-download endpoint with empty
 * bytes so failed loads don't bleed into the test report.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const CONFLICT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc";

const baseExcerpt = (side: "A" | "B") => ({
  document_id: `${side === "A" ? "11111111" : "22222222"}-aaaa-aaaa-aaaa-aaaaaaaaaaaa`,
  drawing_number: side === "A" ? "A-101" : "S-301",
  discipline: side === "A" ? "architectural" : "structural",
  page: 2,
  excerpt: `Excerpt from doc ${side}: slab thickness shown.`,
  bbox: null,
});

const conflictPayload = {
  id: CONFLICT_ID,
  organization_id: ORG_ID,
  project_id: PROJECT_ID,
  status: "open" as const,
  severity: "critical" as const,
  conflict_type: "dimension" as const,
  description: "Slab thickness mismatch: A-101 says 200mm, S-301 says 180mm",
  document_a_id: null,
  chunk_a_id: null,
  document_b_id: null,
  chunk_b_id: null,
  ai_explanation:
    "Architectural drawing shows 200mm; structural drawing shows 180mm. Likely structural is correct — confirm with engineer.",
  resolution_notes: null,
  detected_at: "2026-04-20T08:00:00Z",
  resolved_at: null,
  resolved_by: null,
  document_a: baseExcerpt("A"),
  document_b: baseExcerpt("B"),
};

test.describe("Drawbridge / Conflict detail", () => {
  test.beforeEach(async ({ page }) => {
    // Soak up PDF-download requests so unmocked-network noise doesn't
    // pollute the trace on failure.
    await page.route("**/api/v1/drawbridge/documents/*/file", async (r) => {
      await r.fulfill({ status: 200, contentType: "application/pdf", body: "" });
    });
  });

  test("renders pills, AI explanation, and both excerpt panes", async ({ page }) => {
    await page.route(
      `**/api/v1/drawbridge/conflicts/${CONFLICT_ID}`,
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: conflictPayload, meta: null, errors: null }),
        });
      },
    );

    await page.goto(`/drawbridge/conflicts/${CONFLICT_ID}`);

    // Pills
    await expect(page.getByText(/nghiêm trọng/i)).toBeVisible();
    await expect(page.getByText("open", { exact: true })).toBeVisible();
    await expect(page.getByText("dimension")).toBeVisible();

    // Description as the page title
    await expect(
      page.getByText(/Slab thickness mismatch: A-101 says 200mm, S-301 says 180mm/),
    ).toBeVisible();

    // AI explanation banner
    await expect(page.getByText(/Phân tích AI/i)).toBeVisible();
    await expect(
      page.getByText(/Architectural drawing shows 200mm/),
    ).toBeVisible();

    // Both excerpt panes (titles + drawing numbers)
    await expect(page.getByText("Tài liệu A")).toBeVisible();
    await expect(page.getByText("Tài liệu B")).toBeVisible();
    await expect(page.getByRole("link", { name: "A-101" })).toBeVisible();
    await expect(page.getByRole("link", { name: "S-301" })).toBeVisible();
  });

  test("'Tạo RFI' POSTs to /rfis/generate with conflict_id and redirects", async ({ page }) => {
    await page.route(
      `**/api/v1/drawbridge/conflicts/${CONFLICT_ID}`,
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: conflictPayload, meta: null, errors: null }),
        });
      },
    );

    // List endpoint after redirect — no-op.
    await page.route("**/api/v1/drawbridge/rfis*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 200, total: 0 },
          errors: null,
        }),
      });
    });

    let generateBody: unknown = null;
    const generateSeen = page.waitForRequest(
      (r) =>
        r.url().endsWith("/api/v1/drawbridge/rfis/generate") &&
        r.method() === "POST",
    );

    await page.route(
      "**/api/v1/drawbridge/rfis/generate",
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        generateBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
              number: "RFI-005",
              subject: "Resolve slab thickness conflict",
              status: "open",
              priority: "high",
            },
            meta: null,
            errors: null,
          }),
        });
      },
    );

    await page.goto(`/drawbridge/conflicts/${CONFLICT_ID}`);
    await page.getByRole("button", { name: /tạo rfi/i }).click();

    const req = await generateSeen;
    expect(req.method()).toBe("POST");
    expect(generateBody).toMatchObject({ conflict_id: CONFLICT_ID });

    // The page navigates to /drawbridge/rfis on success
    await expect(page).toHaveURL(/\/drawbridge\/rfis$/);
  });

  test("'Đánh dấu đã xử lý' PATCHes status:resolved with notes", async ({ page }) => {
    await page.route(
      `**/api/v1/drawbridge/conflicts/${CONFLICT_ID}`,
      async (route: Route) => {
        const m = route.request().method();
        if (m === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ data: conflictPayload, meta: null, errors: null }),
          });
          return;
        }
        if (m === "PATCH") {
          patchBody = route.request().postDataJSON();
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              data: {
                ...conflictPayload,
                status: "resolved",
                resolved_at: "2026-04-25T08:00:00Z",
              },
              meta: null,
              errors: null,
            }),
          });
          return;
        }
        return route.fallback();
      },
    );

    // Conflicts list endpoint after redirect.
    await page.route("**/api/v1/drawbridge/conflicts*", async (route: Route) => {
      const url = route.request().url();
      if (url.includes(`/conflicts/${CONFLICT_ID}`)) return route.fallback();
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

    let patchBody: unknown = null;
    const patchSeen = page.waitForRequest(
      (r) =>
        r.url().includes(`/api/v1/drawbridge/conflicts/${CONFLICT_ID}`) &&
        r.method() === "PATCH",
    );

    await page.goto(`/drawbridge/conflicts/${CONFLICT_ID}`);

    await page
      .getByPlaceholder(/Mô tả cách xử lý xung đột/)
      .fill("Used the structural value: 180mm.");

    await page.getByRole("button", { name: /đánh dấu đã xử lý/i }).click();

    const req = await patchSeen;
    expect(req.method()).toBe("PATCH");
    expect(patchBody).toMatchObject({
      status: "resolved",
      resolution_notes: "Used the structural value: 180mm.",
    });

    await expect(page).toHaveURL(/\/drawbridge\/conflicts$/);
  });
});
