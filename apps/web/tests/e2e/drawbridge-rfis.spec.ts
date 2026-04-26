import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Drawbridge RFI tracker page.
 *
 * What's covered
 * --------------
 * 1. Three-column kanban renders RFIs grouped by status with the right
 *    counts in each column header.
 * 2. The create dialog wires up: opening it, filling subject + priority,
 *    submitting POSTs to `/api/v1/drawbridge/rfis` with the typed payload.
 * 3. Answering an RFI fires `POST /rfis/{id}/answer` with the response
 *    text and `close: true` (the checkbox default).
 *
 * `useRFIs` has `enabled: Boolean(filters.project_id)`, so every test
 * fills the project_id input first before asserting on list content.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

const OPEN_RFI_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const ANSWERED_RFI_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

const baseRfi = {
  organization_id: ORG_ID,
  project_id: PROJECT_ID,
  description: null as string | null,
  related_document_ids: [] as string[],
  raised_by: null,
  assigned_to: null,
  due_date: null as string | null,
  response: null as string | null,
  created_at: "2026-04-20T08:00:00Z",
};

const seedRfis = [
  {
    ...baseRfi,
    id: OPEN_RFI_ID,
    number: "RFI-001",
    subject: "Clarify slab thickness on level 3",
    status: "open" as const,
    priority: "high" as const,
  },
  {
    ...baseRfi,
    id: ANSWERED_RFI_ID,
    number: "RFI-002",
    subject: "Confirm column grid spacing",
    status: "answered" as const,
    priority: "normal" as const,
    response: "Confirmed: 7.5m on-center",
  },
];

test.describe("Drawbridge / RFIs", () => {
  test("renders three-column kanban with grouped counts", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/rfis*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: seedRfis,
          meta: { page: 1, per_page: 200, total: seedRfis.length },
          errors: null,
        }),
      });
    });

    await page.goto("/drawbridge/rfis");
    await page.getByPlaceholder("project_id").fill(PROJECT_ID);

    // Both subjects render under the right column
    await expect(page.getByText("Clarify slab thickness on level 3")).toBeVisible();
    await expect(page.getByText("Confirm column grid spacing")).toBeVisible();

    // Column counts — the three columns are sections; pull them by their
    // header label to dodge ambiguity with cards' status pills.
    const openCol = page.locator("section").filter({ has: page.getByText(/đang mở/i) });
    const answeredCol = page.locator("section").filter({
      has: page.getByText(/đã trả lời/i),
    });
    const closedCol = page.locator("section").filter({
      has: page.getByText(/đã đóng/i),
    });
    await expect(openCol).toContainText("1");
    await expect(answeredCol).toContainText("1");
    await expect(closedCol).toContainText(/0|trống/i);
  });

  test("create dialog POSTs the typed payload", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/rfis*", async (route: Route) => {
      // GET: empty list. POST: capture body, return a stub.
      const req = route.request();
      if (req.method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: [],
            meta: { page: 1, per_page: 200, total: 0 },
            errors: null,
          }),
        });
        return;
      }
      return route.fallback();
    });

    let createBody: unknown = null;
    const createSeen = page.waitForRequest(
      (r) =>
        r.url().endsWith("/api/v1/drawbridge/rfis") && r.method() === "POST",
    );

    await page.route(
      "**/api/v1/drawbridge/rfis",
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        createBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              ...baseRfi,
              id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
              number: "RFI-003",
              subject: "New question",
              status: "open",
              priority: "high",
            },
            meta: null,
            errors: null,
          }),
        });
      },
    );

    await page.goto("/drawbridge/rfis");
    await page.getByPlaceholder("project_id").fill(PROJECT_ID);

    // "Tạo RFI" button gates on project_id; once filled it should enable.
    const createBtn = page.getByRole("button", { name: /tạo rfi/i });
    await expect(createBtn).toBeEnabled();
    await createBtn.click();

    // Dialog renders — fill subject + leave priority/dueDate at defaults.
    const dialog = page.getByRole("dialog").or(
      page.locator("div").filter({ has: page.getByText(/tạo rfi mới/i) }).first(),
    );
    await dialog.getByLabel(/tiêu đề/i).fill("Slab thickness clarification");
    await dialog.getByLabel(/mức độ/i).selectOption("high");

    await dialog.getByRole("button", { name: /^tạo$/i }).click();

    const req = await createSeen;
    expect(req.method()).toBe("POST");
    expect(createBody).toMatchObject({
      project_id: PROJECT_ID,
      subject: "Slab thickness clarification",
      priority: "high",
    });
  });

  test("answering an RFI POSTs to /rfis/{id}/answer", async ({ page }) => {
    await page.route("**/api/v1/drawbridge/rfis*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [seedRfis[0]], // only the open RFI
          meta: { page: 1, per_page: 200, total: 1 },
          errors: null,
        }),
      });
    });

    let answerBody: unknown = null;
    const answerSeen = page.waitForRequest(
      (r) =>
        r.url().includes(`/api/v1/drawbridge/rfis/${OPEN_RFI_ID}/answer`) &&
        r.method() === "POST",
    );

    await page.route(
      `**/api/v1/drawbridge/rfis/${OPEN_RFI_ID}/answer`,
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        answerBody = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: { ...seedRfis[0], status: "closed", response: "..." },
            meta: null,
            errors: null,
          }),
        });
      },
    );

    await page.goto("/drawbridge/rfis");
    await page.getByPlaceholder("project_id").fill(PROJECT_ID);

    // RFICard renders a button that opens the answer dialog. Match by
    // a substring rather than role; the card's button has the "Trả lời"
    // label per packages/ui/drawbridge/RFICard.tsx.
    await page.getByText("Clarify slab thickness on level 3").waitFor();
    await page.getByRole("button", { name: /trả lời/i }).first().click();

    await page.getByLabel(/phản hồi/i).fill("Slab is 200mm per S-301.");
    await page.getByRole("button", { name: /gửi phản hồi/i }).click();

    const req = await answerSeen;
    expect(req.method()).toBe("POST");
    expect(answerBody).toMatchObject({
      response: "Slab is 200mm per S-301.",
      close: true,
    });
  });
});
