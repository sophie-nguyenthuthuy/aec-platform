import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: SchedulePilot.
 *
 * 1. List render — counters render, status badge visible.
 * 2. Detail render — bars on a tiny 3-activity chain, risk panel pulls
 *    `top_risks` from a seeded latest_risk_assessment.
 *
 * The CPM math itself is exercised by `apps/ml/tests/test_schedulepilot_cpm.py`
 * — this file only verifies UI plumbing.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";

test.describe("Schedule / list", () => {
  test("renders schedule cards with counters", async ({ page }) => {
    const items = [
      {
        id: "11111111-1111-1111-1111-111111111111",
        organization_id: ORG_ID,
        project_id: "22222222-2222-2222-2222-222222222222",
        name: "Tower A — master",
        status: "baselined",
        baseline_set_at: "2026-04-01T09:00:00Z",
        data_date: "2026-04-25",
        created_at: "2026-03-15T09:00:00Z",
        updated_at: "2026-04-25T09:00:00Z",
        activity_count: 12,
        on_critical_path_count: 4,
        behind_schedule_count: 2,
        percent_complete: 47.5,
      },
    ];

    await page.route("**/api/v1/schedule/schedules?*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: items,
          meta: { page: 1, per_page: 20, total: 1 },
          errors: null,
        }),
      });
    });

    await page.goto("/schedule");

    await expect(page.getByText("Tower A — master")).toBeVisible();
    await expect(page.getByText("baselined", { exact: true })).toBeVisible();
    await expect(page.getByText("48%")).toBeVisible();
  });
});

test.describe("Schedule / detail", () => {
  test("renders Gantt rows + risk panel when assessment exists", async ({
    page,
  }) => {
    const sid = "33333333-3333-3333-3333-333333333333";
    const a1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const a2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
    const a3 = "cccccccc-cccc-cccc-cccc-cccccccccccc";

    const detail = {
      schedule: {
        id: sid,
        organization_id: ORG_ID,
        project_id: "22222222-2222-2222-2222-222222222222",
        name: "Tower A — master",
        status: "active",
        baseline_set_at: "2026-04-01T09:00:00Z",
        data_date: "2026-04-25",
        created_at: "2026-03-15T09:00:00Z",
        updated_at: "2026-04-25T09:00:00Z",
        activity_count: 3,
        on_critical_path_count: 3,
        behind_schedule_count: 1,
        percent_complete: 50,
      },
      activities: [
        {
          id: a1,
          organization_id: ORG_ID,
          schedule_id: sid,
          code: "A",
          name: "Móng",
          activity_type: "task",
          planned_start: "2026-01-01",
          planned_finish: "2026-01-10",
          planned_duration_days: 10,
          baseline_start: "2026-01-01",
          baseline_finish: "2026-01-10",
          actual_start: "2026-01-01",
          actual_finish: "2026-01-12",
          percent_complete: 100,
          status: "complete",
          assignee_id: null,
          notes: null,
          sort_order: 0,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-12T00:00:00Z",
        },
        {
          id: a2,
          organization_id: ORG_ID,
          schedule_id: sid,
          code: "B",
          name: "Cột & vách",
          activity_type: "task",
          planned_start: "2026-01-13",
          planned_finish: "2026-01-25",
          planned_duration_days: 13,
          baseline_start: "2026-01-13",
          baseline_finish: "2026-01-25",
          actual_start: "2026-01-13",
          actual_finish: null,
          percent_complete: 50,
          status: "in_progress",
          assignee_id: null,
          notes: null,
          sort_order: 1,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-04-25T00:00:00Z",
        },
        {
          id: a3,
          organization_id: ORG_ID,
          schedule_id: sid,
          code: "C",
          name: "Mái",
          activity_type: "task",
          planned_start: "2026-01-26",
          planned_finish: "2026-02-05",
          planned_duration_days: 11,
          baseline_start: "2026-01-26",
          baseline_finish: "2026-02-05",
          actual_start: null,
          actual_finish: null,
          percent_complete: 0,
          status: "not_started",
          assignee_id: null,
          notes: null,
          sort_order: 2,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      dependencies: [],
      latest_risk_assessment: {
        id: "44444444-4444-4444-4444-444444444444",
        organization_id: ORG_ID,
        schedule_id: sid,
        generated_at: "2026-04-25T12:00:00Z",
        model_version: "schedulepilot/v1@claude-test",
        data_date_used: "2026-04-25",
        overall_slip_days: 7,
        confidence_pct: 75,
        critical_path_codes: ["A", "B", "C"],
        top_risks: [
          {
            activity_id: a2,
            code: "B",
            name: "Cột & vách",
            expected_slip_days: 7,
            reason: "50% complete and tracking past baseline finish",
            mitigation: "Add a second concrete crew on weekends",
          },
        ],
        input_summary: { activity_count: 3 },
        notes: null,
      },
    };

    await page.route(`**/api/v1/schedule/schedules/${sid}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: detail, meta: null, errors: null }),
      });
    });

    await page.goto(`/schedule/${sid}`);

    await expect(
      page.getByRole("heading", { name: "Tower A — master" }),
    ).toBeVisible();

    // Activity rows
    for (const code of ["A", "B", "C"]) {
      await expect(page.getByText(code, { exact: true }).first()).toBeVisible();
    }
    // The activity-name strings appear once in the Gantt-row label *and*
    // once in the AI risk panel ("B · Cột & vách"), so a plain getByText
    // hits two nodes. `.first()` scopes to the row label which is what
    // these visibility checks care about.
    await expect(page.getByText("Móng").first()).toBeVisible();
    await expect(page.getByText("Cột & vách").first()).toBeVisible();
    await expect(page.getByText("Mái").first()).toBeVisible();

    // Risk panel. `/7 ngày/` resolves to both the headline duration ("7 ngày")
    // and the activity-impact chip ("+7 ngày"); `.first()` picks the headline.
    await expect(page.getByText(/Phân tích rủi ro AI/i)).toBeVisible();
    await expect(page.getByText(/7 ngày/).first()).toBeVisible();
    await expect(page.getByText(/A → B → C/)).toBeVisible();
    await expect(page.getByText(/Add a second concrete crew/)).toBeVisible();
  });
});
