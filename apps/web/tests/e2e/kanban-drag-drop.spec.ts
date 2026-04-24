import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Kanban drag-drop triggers the optimistic update *before* the server
 * responds, then the bulk-mutation PATCH lands with the right payload.
 *
 * Strategy
 * --------
 * - Intercept `GET /api/v1/pulse/tasks` to return a fixed seed list with one
 *   "todo" card and one "done" card.
 * - Intercept `POST /api/v1/pulse/tasks/bulk` and **hold** the response for
 *   ~1.2s — long enough to prove the UI moves the card *before* the server
 *   answers. That's the whole point of an optimistic update; if the test
 *   doesn't deliberately slow the mutation it can pass without exercising the
 *   optimistic path.
 * - Drive HTML5 native drag via `page.evaluateHandle(() => new DataTransfer())`
 *   + `dispatchEvent("dragstart" / "drop")`. `locator.dragTo()` alone doesn't
 *   trigger `dataTransfer.setData/getData` reliably in Chromium — the explicit
 *   DataTransfer handle does.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const TODO_TASK_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const DONE_TASK_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

const seedTasks = [
  {
    id: TODO_TASK_ID,
    organization_id: ORG_ID,
    project_id: PROJECT_ID,
    parent_id: null,
    title: "Review structural drawings",
    description: null,
    status: "todo",
    priority: "normal",
    assignee_id: null,
    phase: "design",
    discipline: null,
    start_date: null,
    due_date: null,
    completed_at: null,
    position: 1,
    tags: [],
    created_by: null,
    created_at: "2026-04-20T00:00:00Z",
  },
  {
    id: DONE_TASK_ID,
    organization_id: ORG_ID,
    project_id: PROJECT_ID,
    parent_id: null,
    title: "Kick-off meeting minutes",
    description: null,
    status: "done",
    priority: "normal",
    assignee_id: null,
    phase: "design",
    discipline: null,
    start_date: null,
    due_date: null,
    completed_at: "2026-04-15T10:00:00Z",
    position: 1,
    tags: [],
    created_by: null,
    created_at: "2026-04-14T00:00:00Z",
  },
];

test.describe("Pulse Kanban", () => {
  test("drag from todo → in_progress applies optimistically, then PATCHes", async ({
    page,
  }) => {
    // --- Stub GET /tasks ---------------------------------------------------
    await page.route("**/api/v1/pulse/tasks*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: seedTasks,
          meta: { page: 1, per_page: 200, total: seedTasks.length },
          errors: null,
        }),
      });
    });

    // --- Stub POST /tasks/bulk with a deliberate delay ---------------------
    let bulkRequestBody: unknown = null;
    const bulkResolved = page.waitForRequest(
      (req) =>
        req.url().includes("/api/v1/pulse/tasks/bulk") &&
        req.method() === "POST",
    );

    await page.route("**/api/v1/pulse/tasks/bulk", async (route: Route) => {
      bulkRequestBody = route.request().postDataJSON();
      // Hold the response so the optimistic update is observable.
      await new Promise((r) => setTimeout(r, 1200));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [
            {
              ...seedTasks[0],
              status: "in_progress",
            },
          ],
          meta: null,
          errors: null,
        }),
      });
    });

    // --- Load the Kanban ---------------------------------------------------
    await page.goto(`/pulse/${PROJECT_ID}/tasks`);

    const todoColumn = page.getByRole("region", { name: /chưa bắt đầu|todo/i });
    const inProgressColumn = page.getByRole("region", {
      name: /đang làm|in progress/i,
    });

    // Card starts in "todo", not in "in_progress".
    await expect(
      todoColumn.getByText("Review structural drawings"),
    ).toBeVisible();
    await expect(
      inProgressColumn.getByText("Review structural drawings"),
    ).toHaveCount(0);

    // --- Drag (HTML5 native) ----------------------------------------------
    const source = todoColumn.getByText("Review structural drawings");
    const sourceDraggable = source.locator("xpath=ancestor::div[@draggable='true'][1]");

    const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
    await sourceDraggable.dispatchEvent("dragstart", { dataTransfer });
    await inProgressColumn.dispatchEvent("dragover", { dataTransfer });
    await inProgressColumn.dispatchEvent("drop", { dataTransfer });

    // --- Optimistic assertion ---------------------------------------------
    // Card should appear in the new column immediately, *before* bulk resolves.
    await expect(
      inProgressColumn.getByText("Review structural drawings"),
    ).toBeVisible({ timeout: 500 });
    await expect(
      todoColumn.getByText("Review structural drawings"),
    ).toHaveCount(0);

    // --- Network contract --------------------------------------------------
    const bulkReq = await bulkResolved;
    expect(bulkReq.headers()["x-org-id"]).toBe(ORG_ID);

    // Wait for the mocked response so we also verify the onSettled invalidate
    // doesn't throw the card back.
    await bulkReq.response();

    expect(bulkRequestBody).toMatchObject({
      items: [{ id: TODO_TASK_ID, status: "in_progress" }],
    });

    // Card should stay put after the server confirms.
    await expect(
      inProgressColumn.getByText("Review structural drawings"),
    ).toBeVisible();
  });

  test("rolls back card position when the bulk PATCH fails", async ({ page }) => {
    await page.route("**/api/v1/pulse/tasks*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: seedTasks,
          meta: { page: 1, per_page: 200, total: seedTasks.length },
          errors: null,
        }),
      });
    });

    await page.route("**/api/v1/pulse/tasks/bulk", async (route: Route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          data: null,
          errors: [{ code: "internal", message: "boom" }],
        }),
      });
    });

    await page.goto(`/pulse/${PROJECT_ID}/tasks`);

    const todoColumn = page.getByRole("region", { name: /chưa bắt đầu|todo/i });
    const inProgressColumn = page.getByRole("region", {
      name: /đang làm|in progress/i,
    });

    const source = todoColumn.getByText("Review structural drawings");
    const sourceDraggable = source.locator("xpath=ancestor::div[@draggable='true'][1]");

    const dataTransfer = await page.evaluateHandle(() => new DataTransfer());
    await sourceDraggable.dispatchEvent("dragstart", { dataTransfer });
    await inProgressColumn.dispatchEvent("dragover", { dataTransfer });
    await inProgressColumn.dispatchEvent("drop", { dataTransfer });

    // After the server returns 500, the onError handler should restore the
    // previous cache and the card should land back in "todo".
    await expect(
      todoColumn.getByText("Review structural drawings"),
    ).toBeVisible({ timeout: 3000 });
    await expect(
      inProgressColumn.getByText("Review structural drawings"),
    ).toHaveCount(0);
  });
});
