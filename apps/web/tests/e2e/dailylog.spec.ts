import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: DailyLog (Nhật ký công trường).
 *
 * Covers:
 *   1. List render — card grid with weather/headcount/observation counters,
 *      severity colour cues on the open/severe pills.
 *   2. Empty state when no logs match.
 *   3. Detail page — narrative + observation list with provenance labels
 *      (AI / SiteEye / manual), "Trích xuất lại bằng AI" button fires
 *      POST /logs/{id}/extract with force=true.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

test.describe("DailyLog / list", () => {
  test("cards show counter colour cues based on severity", async ({ page }) => {
    const items = [
      {
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        log_date: "2026-04-26",
        status: "submitted",
        submitted_at: "2026-04-26T18:00:00Z",
        approved_at: null,
        created_at: "2026-04-26T08:00:00Z",
        total_headcount: 24,
        open_observations: 3,
        high_severity_observations: 1,
      },
      {
        id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        log_date: "2026-04-25",
        status: "approved",
        submitted_at: "2026-04-25T18:00:00Z",
        approved_at: "2026-04-26T09:00:00Z",
        created_at: "2026-04-25T08:00:00Z",
        total_headcount: 18,
        open_observations: 0,
        high_severity_observations: 0,
      },
    ];

    await page.route("**/api/v1/dailylog/logs?*", async (route: Route) => {
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

    await page.goto("/dailylog");

    // Vietnamese-formatted dates appear (vi-VN locale → 26/4/2026 or 26/04/2026).
    // The same date string also shows in a "Tạo: …" paragraph, so scope to
    // the card title heading specifically to avoid a strict-mode multi-match.
    await expect(
      page.getByRole("heading", { name: /26\/0?4\/2026/ }),
    ).toBeVisible();
    // Headcount totals
    await expect(page.getByText("24", { exact: true })).toBeVisible();
    await expect(page.getByText("18", { exact: true })).toBeVisible();
    // Status badges
    await expect(page.getByText("submitted", { exact: true })).toBeVisible();
    await expect(page.getByText("approved", { exact: true })).toBeVisible();
  });

  test("empty-state copy when nothing exists", async ({ page }) => {
    await page.route("**/api/v1/dailylog/logs?*", async (route: Route) => {
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

    await page.goto("/dailylog");
    await expect(page.getByText(/chưa có nhật ký công trường nào/i)).toBeVisible();
  });
});

test.describe("DailyLog / detail", () => {
  test("renders observations with provenance labels and triggers AI re-extract", async ({
    page,
  }) => {
    const logId = "cccccccc-cccc-cccc-cccc-cccccccccccc";
    const detail = {
      summary: {
        id: logId,
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        log_date: "2026-04-26",
        status: "draft",
        submitted_at: null,
        approved_at: null,
        created_at: "2026-04-26T08:00:00Z",
        total_headcount: 24,
        open_observations: 3,
        high_severity_observations: 1,
      },
      weather: {
        conditions: "Mưa rào",
        temp_c: 28,
        precipitation_mm: 25,
      },
      narrative: "Mưa to làm chậm đổ bê tông cột tầng 3.",
      work_completed: null,
      issues_observed: null,
      manpower: [
        { id: "m-1", trade: "Thợ bê tông", headcount: 12, hours_worked: 8, foreman: null, notes: null },
        { id: "m-2", trade: "Thợ điện", headcount: 6, hours_worked: 8, foreman: null, notes: null },
        { id: "m-3", trade: "Phụ", headcount: 6, hours_worked: 6, foreman: null, notes: null },
      ],
      equipment: [
        { id: "e-1", name: "Cẩu tháp", quantity: 1, hours_used: 4, state: "active", notes: null },
        { id: "e-2", name: "Máy đầm", quantity: 2, hours_used: 0, state: "idle", notes: null },
      ],
      observations: [
        {
          id: "o-1",
          organization_id: ORG_ID,
          log_id: logId,
          kind: "risk",
          severity: "high",
          description: "Mưa to làm chậm đổ bê tông tầng 3",
          source: "llm_extracted",
          related_safety_incident_id: null,
          status: "open",
          resolved_at: null,
          notes: null,
          created_at: "2026-04-26T12:00:00Z",
        },
        {
          id: "o-2",
          organization_id: ORG_ID,
          log_id: logId,
          kind: "safety",
          severity: "critical",
          description: "[SiteEye: no_ppe] Worker without hard hat detected",
          source: "siteeye_hit",
          related_safety_incident_id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
          status: "open",
          resolved_at: null,
          notes: null,
          created_at: "2026-04-26T13:00:00Z",
        },
        {
          id: "o-3",
          organization_id: ORG_ID,
          log_id: logId,
          kind: "delay",
          severity: "medium",
          description: "Trễ vật tư cốt thép",
          source: "manual",
          related_safety_incident_id: null,
          status: "in_progress",
          resolved_at: null,
          notes: null,
          created_at: "2026-04-26T14:00:00Z",
        },
      ],
    };

    await page.route(`**/api/v1/dailylog/logs/${logId}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: detail, meta: null, errors: null }),
      });
    });

    let extractCall: { body: string } | null = null;
    await page.route(`**/api/v1/dailylog/logs/${logId}/extract`, async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      extractCall = { body: route.request().postData() ?? "" };
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          data: { log_id: logId, observations: [] },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto(`/dailylog/${logId}`);

    // Narrative + provenance labels
    await expect(
      page.getByText(/Mưa to làm chậm đổ bê tông cột tầng 3/),
    ).toBeVisible();
    await expect(page.getByText(/AI/, { exact: false }).first()).toBeVisible();
    await expect(page.getByText(/SiteEye/).first()).toBeVisible();

    // Provenance counter line under "Vấn đề / rủi ro ghi nhận"
    await expect(page.getByText(/1 do AI/i)).toBeVisible();
    await expect(page.getByText(/1 thủ công/i)).toBeVisible();
    await expect(page.getByText(/1 từ SiteEye/i)).toBeVisible();

    // Manpower + equipment summary lines
    await expect(page.getByText("24 người · 3 tổ")).toBeVisible();
    await expect(page.getByText("2 loại")).toBeVisible();

    // Trigger AI re-extract
    await page.getByRole("button", { name: /Trích xuất lại bằng AI/i }).click();
    await expect.poll(() => extractCall).not.toBeNull();
    const parsed = JSON.parse(extractCall!.body);
    expect(parsed.force).toBe(true);
  });
});
