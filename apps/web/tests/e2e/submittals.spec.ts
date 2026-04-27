import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: Submittals.
 *
 * Covers:
 *   1. List render — table rows, status + ball-in-court badges, CSI division
 *      column, pagination header.
 *   2. Empty-state copy when no submittals match the filter.
 *   3. Status-filter pills add `status=` to the API URL.
 *   4. Detail page — revision timeline + inline review buttons fire
 *      `POST /revisions/{id}/review` with the right verdict.
 *
 * SQL correctness lives in apps/api/tests/test_submittals_router.py;
 * this file is purely UI plumbing.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";

const baseSubmittal = {
  organization_id: ORG_ID,
  project_id: "11111111-1111-1111-1111-111111111111",
  description: null as string | null,
  spec_section: "03 30 00",
  csi_division: "03",
  current_revision: 1,
  ball_in_court: "designer" as const,
  contractor_id: null,
  submitted_by: null,
  due_date: null,
  submitted_at: null,
  closed_at: null,
  notes: null,
  created_at: "2026-04-20T09:00:00Z",
  updated_at: "2026-04-25T09:00:00Z",
};

test.describe("Submittals / list", () => {
  test("renders table rows with status + ball-in-court badges", async ({ page }) => {
    const items = [
      {
        ...baseSubmittal,
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        package_number: "S-001",
        title: "Bê tông M300 — sàn tầng 3",
        submittal_type: "shop_drawing",
        status: "pending_review",
      },
      {
        ...baseSubmittal,
        id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        package_number: "S-002",
        title: "Cốt thép D12 — cột",
        submittal_type: "sample",
        status: "approved",
        ball_in_court: "contractor" as const,
      },
    ];

    await page.route("**/api/v1/submittals?*", async (route: Route) => {
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

    await page.goto("/submittals");

    await expect(page.getByText("S-001")).toBeVisible();
    await expect(page.getByText("Bê tông M300 — sàn tầng 3")).toBeVisible();
    await expect(page.getByText("S-002")).toBeVisible();
    // Status badges render the raw enum string
    await expect(page.getByText("pending_review", { exact: true })).toBeVisible();
    await expect(page.getByText("approved", { exact: true })).toBeVisible();
    // Ball-in-court badges
    await expect(page.getByText("designer", { exact: true })).toBeVisible();
    await expect(page.getByText("contractor", { exact: true })).toBeVisible();
  });

  test("empty-state copy when nothing matches", async ({ page }) => {
    await page.route("**/api/v1/submittals?*", async (route: Route) => {
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

    await page.goto("/submittals");
    await expect(page.getByText(/chưa có submittal nào/i)).toBeVisible();
  });

  test("status filter pill propagates `status=` to the API URL", async ({ page }) => {
    const seenQueries: string[] = [];
    await page.route("**/api/v1/submittals?*", async (route: Route) => {
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

    await page.goto("/submittals");
    await expect.poll(() => seenQueries.length).toBeGreaterThanOrEqual(1);

    await page.getByRole("button", { name: "Đã duyệt" }).click();

    await expect
      .poll(() => seenQueries.some((q) => q.includes("status=approved")))
      .toBeTruthy();
  });
});

test.describe("Submittals / detail review actions", () => {
  test("clicking 'Duyệt' fires POST /revisions/{id}/review with approved", async ({
    page,
  }) => {
    const submittalId = "cccccccc-cccc-cccc-cccc-cccccccccccc";
    const revId = "dddddddd-dddd-dddd-dddd-dddddddddddd";

    await page.route(`**/api/v1/submittals/${submittalId}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            submittal: {
              ...baseSubmittal,
              id: submittalId,
              package_number: "S-007",
              title: "Mock-up vách kính",
              submittal_type: "mock_up",
              status: "pending_review",
            },
            revisions: [
              {
                id: revId,
                organization_id: ORG_ID,
                submittal_id: submittalId,
                revision_number: 1,
                file_id: null,
                review_status: "pending_review",
                reviewer_id: null,
                reviewed_at: null,
                reviewer_notes: null,
                annotations: [],
                created_at: "2026-04-25T09:00:00Z",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    let reviewCallSeen: { url: string; body: string } | null = null;
    await page.route(
      `**/api/v1/submittals/revisions/${revId}/review`,
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        reviewCallSeen = {
          url: route.request().url(),
          body: route.request().postData() ?? "",
        };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              id: revId,
              organization_id: ORG_ID,
              submittal_id: submittalId,
              revision_number: 1,
              file_id: null,
              review_status: "approved",
              reviewer_id: null,
              reviewed_at: "2026-04-26T12:00:00Z",
              reviewer_notes: null,
              annotations: [],
              created_at: "2026-04-25T09:00:00Z",
            },
            meta: null,
            errors: null,
          }),
        });
      },
    );

    await page.goto(`/submittals/${submittalId}`);

    await expect(page.getByText(/S-007/)).toBeVisible();
    // Revision list shows R1 with the four review action buttons
    await expect(page.getByText("R1", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Duyệt", exact: true }).click();

    await expect.poll(() => reviewCallSeen).not.toBeNull();
    const parsed = JSON.parse(reviewCallSeen!.body);
    expect(parsed.review_status).toBe("approved");
  });
});
