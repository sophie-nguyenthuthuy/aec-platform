import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: ChangeOrder.
 *
 * Covers:
 *   1. List render — table with status + cost/time impact, status filter
 *      pill propagates `status=` to the API URL.
 *   2. Detail page — line items table + status-transition buttons
 *      (whitelisted by current status). Clicking a transition fires
 *      POST /cos/{id}/approvals with the right `to_status`.
 *   3. CostPulse hint pill on the inline "Add line item" form — the
 *      live `usePriceSuggestions` query lights up once the user types
 *      a description, and clicking a chip pre-fills the unit cost.
 *
 * Backend is covered by apps/api/tests/test_changeorder_router.py.
 */

const ORG_ID = "00000000-0000-0000-0000-000000000000";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

test.describe("ChangeOrder / list", () => {
  test("renders the table with status badges and impact columns", async ({ page }) => {
    const items = [
      {
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        number: "CO-001",
        title: "Đổi vật liệu cửa",
        description: "Owner-requested",
        status: "submitted",
        initiator: "Owner",
        cost_impact_vnd: 18_000_000,
        schedule_impact_days: 3,
        ai_analysis: null,
        submitted_at: "2026-04-25T09:00:00Z",
        approved_at: null,
        approved_by: null,
        created_at: "2026-04-24T09:00:00Z",
      },
      {
        id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        organization_id: ORG_ID,
        project_id: PROJECT_ID,
        number: "CO-002",
        title: "Bổ sung cốt thép",
        description: null,
        status: "approved",
        initiator: "Designer",
        cost_impact_vnd: 5_500_000,
        schedule_impact_days: 0,
        ai_analysis: null,
        submitted_at: null,
        approved_at: "2026-04-26T10:00:00Z",
        approved_by: null,
        created_at: "2026-04-26T08:00:00Z",
      },
    ];

    await page.route("**/api/v1/changeorder/cos?*", async (route: Route) => {
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

    await page.goto("/changeorder");

    await expect(page.getByText("CO-001")).toBeVisible();
    await expect(page.getByText("Đổi vật liệu cửa")).toBeVisible();
    await expect(page.getByText("CO-002")).toBeVisible();
    await expect(page.getByText("submitted", { exact: true })).toBeVisible();
    await expect(page.getByText("approved", { exact: true })).toBeVisible();
    // Cost-impact formatter (M/B suffix with VND symbol).
    await expect(page.getByText(/18M ₫/)).toBeVisible();
    // Schedule impact "3 ngày" cell
    await expect(page.getByText("3 ngày")).toBeVisible();
  });

  test("status pill propagates `status=` to the API URL", async ({ page }) => {
    const seenQueries: string[] = [];
    await page.route("**/api/v1/changeorder/cos?*", async (route: Route) => {
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

    await page.goto("/changeorder");
    await expect.poll(() => seenQueries.length).toBeGreaterThanOrEqual(1);

    await page.getByRole("button", { name: "Đã duyệt" }).click();

    await expect
      .poll(() => seenQueries.some((q) => q.includes("status=approved")))
      .toBeTruthy();
  });
});

test.describe("ChangeOrder / detail", () => {
  const COID = "cccccccc-cccc-cccc-cccc-cccccccccccc";

  function _detail(overrides: Record<string, unknown> = {}) {
    const co = {
      id: COID,
      organization_id: ORG_ID,
      project_id: PROJECT_ID,
      number: "CO-007",
      title: "Bổ sung điều hoà",
      description: null,
      status: "submitted",
      initiator: "Owner",
      cost_impact_vnd: 60_000_000,
      schedule_impact_days: 5,
      ai_analysis: null,
      submitted_at: "2026-04-25T09:00:00Z",
      approved_at: null,
      approved_by: null,
      created_at: "2026-04-24T09:00:00Z",
      ...overrides,
    };
    return {
      change_order: co,
      sources: [],
      line_items: [
        {
          id: "li-1",
          organization_id: ORG_ID,
          change_order_id: COID,
          description: "Điều hoà 24,000 BTU",
          line_kind: "add",
          spec_section: "23 81 00",
          quantity: 4,
          unit: "ea",
          unit_cost_vnd: 15_000_000,
          cost_vnd: 60_000_000,
          schedule_impact_days: 5,
          schedule_activity_id: null,
          sort_order: 0,
          notes: null,
          created_at: "2026-04-24T10:00:00Z",
        },
      ],
      approvals: [
        {
          id: "ap-1",
          organization_id: ORG_ID,
          change_order_id: COID,
          from_status: "draft",
          to_status: "submitted",
          actor_id: null,
          notes: "Trình duyệt",
          created_at: "2026-04-25T09:00:00Z",
        },
      ],
    };
  }

  test("status-transition button fires POST /approvals with the right to_status", async ({
    page,
  }) => {
    await page.route(`**/api/v1/changeorder/cos/${COID}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: _detail(), meta: null, errors: null }),
      });
    });

    let approvalCall: { body: string } | null = null;
    await page.route(`**/api/v1/changeorder/cos/${COID}/approvals`, async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      approvalCall = { body: route.request().postData() ?? "" };
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            id: "ap-2",
            organization_id: ORG_ID,
            change_order_id: COID,
            from_status: "submitted",
            to_status: "reviewed",
            actor_id: null,
            notes: null,
            created_at: "2026-04-26T11:00:00Z",
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto(`/changeorder/${COID}`);

    await expect(page.getByText(/CO-007/)).toBeVisible();
    // The whitelist for status='submitted' shows reviewed/rejected/cancelled.
    await page.getByRole("button", { name: "→ reviewed" }).click();

    await expect.poll(() => approvalCall).not.toBeNull();
    const parsed = JSON.parse(approvalCall!.body);
    expect(parsed.to_status).toBe("reviewed");
  });

  test("CostPulse hint pill fills unit cost when chip is clicked", async ({ page }) => {
    await page.route(`**/api/v1/changeorder/cos/${COID}`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: _detail(), meta: null, errors: null }),
      });
    });

    // Mock the price-suggestions endpoint with one row.
    await page.route("**/api/v1/changeorder/price-suggestions*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            query: "bê tông",
            spec_section: null,
            results: [
              {
                material_price_id: "ma-1",
                material_code: "C30-OPC",
                name: "Bê tông M300 OPC",
                category: "Concrete",
                unit: "m3",
                price_vnd: 1_750_000,
                province: "HCM",
                source: "ministry-april",
                effective_date: "2026-04-01",
              },
            ],
          },
          meta: null,
          errors: null,
        }),
      });
    });

    await page.goto(`/changeorder/${COID}`);

    // Open the inline add-line-item form.
    await page.getByRole("button", { name: "Thêm line item" }).click();
    // Type into description — usePriceSuggestions is enabled when `q` is non-empty.
    await page.getByPlaceholder(/Bê tông M300 sàn tầng 4/i).fill("bê tông");

    // Wait for the hint pill heading to appear, then click the chip.
    await expect(page.getByText(/Gợi ý đơn giá từ CostPulse/i)).toBeVisible();
    await page.getByRole("button", { name: /1\.750\.000 ₫/ }).click();

    // The unit-cost input should now read 1750000 (chip fills it directly).
    const unitCostInput = page.locator('input[type="number"]').nth(1);
    await expect(unitCostInput).toHaveValue("1750000");
  });
});
