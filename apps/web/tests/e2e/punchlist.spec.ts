import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Punch list.
 *
 *   1. List render — card grid with the 3 counter pills + completion bar.
 *   2. Empty state copy.
 *   3. Status filter pill propagates `status=` to the API URL.
 *   4. Detail render — items sorted by item_number, sign-off button is
 *      disabled when any item is still open/in_progress/fixed.
 *   5. Status-transition button on an open item fires PATCH /items/{id}
 *      with the right `status` value.
 *
 * SQL is exercised by apps/api/tests/test_punchlist_router.py;
 * this file only verifies UI plumbing.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

test.describe("Punch list / list", () => {
  test("renders cards with verified/total completion bar", async ({ page }) => {
    const items = [
      {
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        name: "Pre-occupancy walkthrough",
        walkthrough_date: "2026-05-01",
        status: "open",
        owner_attendees: "Owner, GC, Architect",
        notes: null,
        signed_off_at: null,
        signed_off_by: null,
        created_by: null,
        created_at: "2026-05-01T09:00:00Z",
        updated_at: "2026-05-01T09:00:00Z",
        total_items: 12,
        open_items: 4,
        fixed_items: 0,
        verified_items: 8,
      },
      {
        id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        name: "Lobby acceptance",
        walkthrough_date: "2026-04-15",
        status: "signed_off",
        owner_attendees: null,
        notes: null,
        signed_off_at: "2026-04-20T15:00:00Z",
        signed_off_by: null,
        created_by: null,
        created_at: "2026-04-15T09:00:00Z",
        updated_at: "2026-04-20T15:00:00Z",
        total_items: 5,
        open_items: 0,
        fixed_items: 0,
        verified_items: 5,
      },
    ];

    await page.route("**/api/v1/punchlist/lists?*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: items,
          meta: { page: 1, per_page: 20, total: items.length },
          errors: null,
        }),
      });
    });

    await page.goto("/punchlist");

    await expect(page.getByText("Pre-occupancy walkthrough")).toBeVisible();
    await expect(page.getByText("Lobby acceptance")).toBeVisible();
    await expect(page.getByText("open", { exact: true })).toBeVisible();
    await expect(page.getByText("signed_off", { exact: true })).toBeVisible();
    // Completion percentages: 8/12 = 67%, 5/5 = 100%
    await expect(page.getByText("67%")).toBeVisible();
    await expect(page.getByText("100%")).toBeVisible();
  });

  test("empty-state copy when no lists", async ({ page }) => {
    await page.route("**/api/v1/punchlist/lists?*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 20, total: 0 },
          errors: null,
        }),
      });
    });

    await page.goto("/punchlist");
    await expect(page.getByText(/chưa có punch list nào/i)).toBeVisible();
  });

  test("status pill propagates status= to the API URL", async ({ page }) => {
    const seenQueries: string[] = [];
    await page.route("**/api/v1/punchlist/lists?*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      seenQueries.push(new URL(route.request().url()).search);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 20, total: 0 },
          errors: null,
        }),
      });
    });

    await page.goto("/punchlist");
    await expect.poll(() => seenQueries.length).toBeGreaterThanOrEqual(1);

    await page.getByRole("button", { name: "Đã ký" }).click();

    await expect
      .poll(() => seenQueries.some((q) => q.includes("status=signed_off")))
      .toBeTruthy();
  });
});

test.describe("Punch list / detail", () => {
  const LIST_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc";

  function _detail(opts: { allDone: boolean }) {
    const items = [
      {
        id: "i-1",
        organization_id: ORG_ID,
        list_id: LIST_ID,
        item_number: 2,
        description: "Outlet B-103 dead",
        location: "Suite B / Floor 1",
        trade: "mep",
        severity: "high",
        status: opts.allDone ? "verified" : "open",
        photo_id: null,
        assigned_user_id: null,
        due_date: null,
        fixed_at: null,
        verified_at: opts.allDone ? "2026-05-05T10:00:00Z" : null,
        verified_by: null,
        notes: null,
        created_at: "2026-05-01T09:00:00Z",
        updated_at: "2026-05-01T09:00:00Z",
      },
      {
        id: "i-2",
        organization_id: ORG_ID,
        list_id: LIST_ID,
        item_number: 1,
        description: "Vết sơn ở sảnh tầng 1",
        location: "Lobby / Floor 1",
        trade: "architectural",
        severity: "medium",
        status: opts.allDone ? "verified" : "in_progress",
        photo_id: null,
        assigned_user_id: null,
        due_date: null,
        fixed_at: null,
        verified_at: opts.allDone ? "2026-05-05T10:00:00Z" : null,
        verified_by: null,
        notes: null,
        created_at: "2026-05-01T09:00:00Z",
        updated_at: "2026-05-01T09:00:00Z",
      },
    ];
    return {
      list: {
        id: LIST_ID,
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        name: "Pre-occupancy walkthrough",
        walkthrough_date: "2026-05-01",
        status: "open",
        owner_attendees: "Owner, GC, Architect",
        notes: null,
        signed_off_at: null,
        signed_off_by: null,
        created_by: null,
        created_at: "2026-05-01T09:00:00Z",
        updated_at: "2026-05-01T09:00:00Z",
        total_items: items.length,
        open_items: opts.allDone ? 0 : 2,
        fixed_items: 0,
        verified_items: opts.allDone ? items.length : 0,
      },
      items,
    };
  }

  test("renders items sorted by item_number with sign-off disabled", async ({
    page,
  }) => {
    await page.route(`**/api/v1/punchlist/lists/${LIST_ID}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: _detail({ allDone: false }),
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto(`/punchlist/${LIST_ID}`);

    // Item numbers in order — #1 before #2 in the visible list (sorted).
    const numbers = await page.locator("text=/^#\\d+$/").allInnerTexts();
    expect(numbers).toEqual(["#1", "#2"]);

    // Sign-off button is disabled while items are unfinished.
    await expect(page.getByRole("button", { name: /Ký bàn giao/ })).toBeDisabled();
  });

  test("status-transition button fires PATCH /items/{id}", async ({ page }) => {
    await page.route(`**/api/v1/punchlist/lists/${LIST_ID}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: _detail({ allDone: false }),
          meta: null,
          errors: null,
        }),
      });
    });

    let patchCall: { url: string; body: string } | null = null;
    await page.route(`**/api/v1/punchlist/items/i-2`, async (route: Route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      patchCall = {
        url: route.request().url(),
        body: route.request().postData() ?? "",
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: { id: "i-2", status: "verified" },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto(`/punchlist/${LIST_ID}`);

    // The "Xác minh" button on item #1 (id i-2) — click the first match;
    // each item row has its own button bar.
    await page.getByRole("button", { name: "→ Xác minh" }).first().click();

    await expect.poll(() => patchCall).not.toBeNull();
    const parsed = JSON.parse(patchCall!.body);
    expect(parsed.status).toBe("verified");
  });
});
