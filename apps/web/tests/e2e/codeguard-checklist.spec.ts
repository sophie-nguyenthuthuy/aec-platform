import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD permit checklist page (streaming variant).
 *
 * The page now consumes `POST /api/v1/codeguard/permit-checklist/stream`
 * which returns SSE — items arrive as `event: item` frames, terminal
 * `event: done` carries the persisted `checklist_id` that enables the
 * mark-item interaction. Tests mock the stream by returning a single
 * SSE-framed body; the hook's parser handles multi-event bodies because
 * blocks are `\n\n`-delimited.
 *
 * Coverage
 * --------
 * 1. Generate happy path — items render with title + required badge +
 *    regulation_ref. After `done`, the page swaps to the full ChecklistView
 *    (mark-item checkboxes enabled) and the POST body matches the form.
 * 2. Mark-item — clicking the checkbox after `done` fires a
 *    POST /checks/{checklist_id}/mark-item against the id from the
 *    streamed `done` payload.
 * 3. Empty items — `done` arrives with no preceding `item` frames; the
 *    amber "Checklist trống" advisory renders inside the ChecklistView.
 * 4. Generate error — `event: error` mid-stream surfaces the red banner
 *    above the form (form stays filled for retry).
 * 5. Mark-item error — same dismissable inline banner as before.
 */

interface SseEvent {
  event: string;
  data: unknown;
}

function sseBody(events: SseEvent[]): string {
  return events
    .map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

const PROJECT_ID = "77777777-7777-7777-7777-777777777777";

async function fillFormAndGenerate(page: Page) {
  await page.goto("/codeguard/checklist");
  await page.locator("input").first().fill(PROJECT_ID);
  // Jurisdiction defaults to "Hồ Chí Minh", project_type to residential.
  await page.getByRole("button", { name: /tạo checklist/i }).click();
}

test.describe("CODEGUARD / Checklist (streaming)", () => {
  test("streams items and reveals the ChecklistView on done", async ({ page }) => {
    let lastBody: unknown = null;
    const checklistId = "88888888-8888-8888-8888-888888888888";

    await page.route("**/api/v1/codeguard/permit-checklist/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "item",
            data: {
              id: "site-survey",
              title: "Khảo sát hiện trạng",
              description: "Bản vẽ khảo sát địa hình và địa chất.",
              regulation_ref: "QCVN 06:2022 §1.1",
              required: true,
              status: "pending",
            },
          },
          {
            event: "item",
            data: {
              id: "fire-approval",
              title: "Phê duyệt PCCC",
              description: null,
              regulation_ref: null,
              required: false,
              status: "pending",
            },
          },
          {
            event: "done",
            data: {
              checklist_id: checklistId,
              total: 2,
              generated_at: "2026-04-27T10:00:00Z",
            },
          },
        ]),
      });
    });

    await fillFormAndGenerate(page);

    // After `done`, page lands in ChecklistView with the full set of
    // items + the 0/2 progress + the mark-item checkboxes available.
    await expect(page.getByText(/Hồ Chí Minh.*residential/)).toBeVisible();
    await expect(page.getByText("0/2")).toBeVisible();
    await expect(page.getByText("Khảo sát hiện trạng")).toBeVisible();
    await expect(page.getByText("Phê duyệt PCCC")).toBeVisible();
    await expect(page.getByText("Bắt buộc")).toBeVisible();
    await expect(page.getByText("QCVN 06:2022 §1.1")).toBeVisible();

    // POST body matches the form.
    expect(lastBody).toMatchObject({
      project_id: PROJECT_ID,
      jurisdiction: "Hồ Chí Minh",
      project_type: "residential",
    });
  });

  test("mark-item targets the checklist_id from the streamed done event", async ({ page }) => {
    const checklistId = "99999999-9999-9999-9999-999999999999";

    await page.route("**/api/v1/codeguard/permit-checklist/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "item",
            data: {
              id: "site-survey",
              title: "Khảo sát hiện trạng",
              description: null,
              regulation_ref: null,
              required: true,
              status: "pending",
            },
          },
          {
            event: "done",
            data: {
              checklist_id: checklistId,
              total: 1,
              generated_at: "2026-04-27T10:00:00Z",
            },
          },
        ]),
      });
    });

    let markBody: unknown = null;
    let markUrl: string | undefined;
    await page.route(`**/api/v1/codeguard/checks/${checklistId}/mark-item`, async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      markBody = route.request().postDataJSON();
      markUrl = route.request().url();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: checklistId,
            project_id: PROJECT_ID,
            jurisdiction: "Hồ Chí Minh",
            project_type: "residential",
            generated_at: "2026-04-27T10:00:00Z",
            completed_at: null,
            items: [
              {
                id: "site-survey",
                title: "Khảo sát hiện trạng",
                description: null,
                regulation_ref: null,
                required: true,
                status: "done",
                updated_at: "2026-04-27T10:01:00Z",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await fillFormAndGenerate(page);
    await expect(page.getByText("0/1")).toBeVisible();

    await page.getByRole("checkbox").click();
    await expect(page.getByText("1/1")).toBeVisible();

    // Mark-item URL contains the SAME checklist_id the streamed `done`
    // event handed off — the page can't make this call until that id
    // arrives.
    expect(markUrl).toContain(`/checks/${checklistId}/mark-item`);
    expect(markBody).toMatchObject({ item_id: "site-survey", status: "done" });
  });

  test("renders the amber empty advisory when done arrives with no items", async ({ page }) => {
    await page.route("**/api/v1/codeguard/permit-checklist/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        // Empty checklist: zero `item` frames before `done`. Pipeline-side
        // tests already cover that the streaming generator produces this
        // shape when the LLM returns `items: []`.
        body: sseBody([
          {
            event: "done",
            data: {
              checklist_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
              total: 0,
              generated_at: "2026-04-27T10:00:00Z",
            },
          },
        ]),
      });
    });

    await fillFormAndGenerate(page);

    await expect(page.getByText("Checklist trống")).toBeVisible();
    await expect(page.getByText(/chưa sinh được mục nào/)).toBeVisible();
    // Reset button is still reachable.
    await expect(page.getByRole("button", { name: /tạo lại/i })).toBeVisible();
  });

  test("shows the red banner when the stream emits an error event", async ({ page }) => {
    await page.route("**/api/v1/codeguard/permit-checklist/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        // The connection succeeded (200) but the pipeline hit a hard
        // failure mid-generation.
        body: sseBody([{ event: "error", data: { message: "Checklist generation failed" } }]),
      });
    });

    await fillFormAndGenerate(page);

    await expect(page.getByText("Lỗi khi tạo checklist")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Checklist generation failed/)).toBeVisible();
    // Form still rendered so the user can retry without re-typing.
    await expect(page.getByRole("button", { name: /tạo checklist/i })).toBeEnabled();
  });

  test("shows a dismissable inline banner when mark-item fails", async ({ page }) => {
    const checklistId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

    await page.route("**/api/v1/codeguard/permit-checklist/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "item",
            data: {
              id: "site-survey",
              title: "Khảo sát hiện trạng",
              description: null,
              regulation_ref: null,
              required: true,
              status: "pending",
            },
          },
          {
            event: "done",
            data: {
              checklist_id: checklistId,
              total: 1,
              generated_at: "2026-04-27T10:00:00Z",
            },
          },
        ]),
      });
    });

    await page.route(`**/api/v1/codeguard/checks/${checklistId}/mark-item`, async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          meta: null,
          errors: [{ code: "bad_gateway", message: "Could not persist status" }],
        }),
      });
    });

    await fillFormAndGenerate(page);
    await page.getByRole("checkbox").click();

    await expect(page.getByText("Không lưu được trạng thái")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Could not persist status/)).toBeVisible();

    await page.getByRole("button", { name: /^đóng$/i }).click();
    await expect(page.getByText("Không lưu được trạng thái")).toHaveCount(0);
  });
});
