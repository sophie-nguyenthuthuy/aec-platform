import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge document library page.
 *
 * What's covered
 * --------------
 * 1. List render — GET /api/v1/drawbridge/documents returns a seeded list,
 *    every row appears in the table, the "N tài liệu" header reflects the
 *    count.
 * 2. Empty state — when the API returns an empty array the user sees the
 *    "Chưa có tài liệu nào" prompt, not a phantom row.
 * 3. Filter controls send query-string params — typing in the search box
 *    and picking a discipline fires a new GET with `q=` and `discipline=`
 *    on the URL. This is the one bit of logic unique to this page that
 *    isn't just plumbing: TanStack Query must refetch with the new key.
 *
 * Why Playwright (vs Vitest + RTL)
 * --------------------------------
 * The page uses `useSession()` from a React context that's only populated
 * via the root `<Providers>` in `app/layout.tsx`. Rendering it in isolation
 * requires rebuilding the whole provider tree. Running it through the real
 * Next.js dev server with `page.route()` mocking keeps the test honest to
 * what the user actually sees and avoids shimming context.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

const baseDoc = {
  id: "",
  organization_id: ORG_ID,
  project_id: PROJECT_ID,
  document_set_id: null,
  file_id: null,
  doc_type: "drawing" as const,
  drawing_number: null as string | null,
  title: null as string | null,
  revision: null as string | null,
  discipline: "architectural" as const,
  scale: null,
  processing_status: "ready" as const,
  extracted_data: {},
  thumbnail_url: null,
  created_at: "2026-04-15T10:00:00Z",
};

test.describe("Drawbridge / Documents", () => {
  test("renders the document list and status badges", async ({ page }) => {
    const docs = [
      {
        ...baseDoc,
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        drawing_number: "A-101",
        title: "Ground floor plan",
        processing_status: "ready" as const,
      },
      {
        ...baseDoc,
        id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        drawing_number: "S-201",
        title: "Column schedule",
        discipline: "structural" as const,
        processing_status: "processing" as const,
      },
    ];

    await page.route("**/api/v1/drawbridge/documents*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: docs,
          meta: { page: 1, per_page: 50, total: docs.length },
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/documents");

    // Header reflects the doc count
    await expect(page.getByText(/2 tài liệu/i)).toBeVisible();

    // Rows render with drawing_number + title + discipline
    await expect(page.getByText("A-101")).toBeVisible();
    await expect(page.getByText("Ground floor plan")).toBeVisible();
    await expect(page.getByText("S-201")).toBeVisible();
    await expect(page.getByText("Column schedule")).toBeVisible();

    // Both status badges render the raw status string
    await expect(page.getByText("ready", { exact: true })).toBeVisible();
    await expect(page.getByText("processing", { exact: true })).toBeVisible();
  });

  test("shows empty-state copy when the list is empty", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/documents*", async (route: Route) => {
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

    await page.goto("/drawbridge/documents");

    await expect(page.getByText(/chưa có tài liệu nào/i)).toBeVisible();
    await expect(page.getByText(/0 tài liệu/i)).toBeVisible();
  });

  test("filter + search inputs are sent as query-string params", async ({ page }) => {
    const seenQueries: string[] = [];

    await page.route("**/api/v1/drawbridge/documents*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      seenQueries.push(new URL(route.request().url()).search);
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

    await page.goto("/drawbridge/documents");
    await expect(page.getByText(/0 tài liệu/i)).toBeVisible();

    // Pick the structural discipline filter
    await page.getByRole("combobox").first().selectOption("structural");

    // Type into the search box
    await page.getByPlaceholder("Tìm kiếm...").fill("column");

    // Each input change bumps the TanStack query key, which fires its own
    // GET. We don't assume a specific ordering — we just wait until *some*
    // fetch carries `q=column`, and separately that *some* fetch carried
    // `discipline=structural`. (Both may land in the same request or in two
    // different ones depending on scheduling.)
    await expect
      .poll(() => seenQueries.some((q) => q.includes("q=column")), {
        timeout: 3000,
      })
      .toBe(true);

    expect(seenQueries.some((q) => q.includes("discipline=structural"))).toBe(
      true,
    );
  });
});
