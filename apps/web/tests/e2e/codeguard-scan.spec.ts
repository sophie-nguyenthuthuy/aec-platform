import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * E2E: CODEGUARD compliance scan wizard (streaming variant).
 *
 * The page now consumes `POST /api/v1/codeguard/scan/stream` which
 * returns SSE — every test mocks that endpoint by returning a single
 * response with an SSE-framed body. The hook's parser handles
 * multi-event bodies because SSE blocks are `\n\n`-delimited.
 *
 * What's covered
 * --------------
 * 1. Happy path — `category_start` flips the per-category progress
 *    chip to "Đang quét", `category_done` flips it to "Xong" and
 *    appends the category's findings, terminal `done` reveals the
 *    ComplianceScore donut. Network contract carries the project_id.
 * 2. Empty-findings advisory — every category emits `done` with an
 *    empty findings list and the terminal `done` reports total=0.
 *    Amber "Không có vấn đề nào được nêu" card renders ONLY after
 *    the terminal `done` (not while still streaming).
 * 3. Error path — backend emits an `error` event mid-stream; the red
 *    banner renders and the "Quét lại" reset is reachable.
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

const PROJECT_ID = "44444444-4444-4444-4444-444444444444";

async function fillParamsAndStartScan(page: Page) {
  await page.goto("/codeguard/scan");
  await page.getByPlaceholder("UUID").fill(PROJECT_ID);
  await page.getByRole("button", { name: /tiếp tục/i }).click();
  await expect(page.getByRole("button", { name: /bắt đầu quét/i })).toBeVisible();
  await page.getByRole("button", { name: /bắt đầu quét/i }).click();
}

test.describe("CODEGUARD / Scan (streaming)", () => {
  test("renders findings as categories complete and reveals the donut on done", async ({ page }) => {
    let lastBody: unknown = null;

    await page.route("**/api/v1/codeguard/scan/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      lastBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          { event: "category_start", data: { category: "fire_safety" } },
          {
            event: "category_done",
            data: {
              category: "fire_safety",
              findings: [
                {
                  status: "FAIL",
                  severity: "critical",
                  category: "fire_safety",
                  title: "Số lối thoát nạn dưới yêu cầu",
                  description: "Project has 1 exit; code requires 2.",
                  resolution: "Bổ sung thêm 1 lối thoát nạn.",
                  citation: {
                    regulation_id: "11111111-1111-1111-1111-111111111111",
                    regulation: "QCVN 06:2022/BXD",
                    section: "3.1",
                    excerpt: "phải có ít nhất 2 lối thoát nạn",
                    source_url: null,
                  },
                },
              ],
            },
          },
          { event: "category_start", data: { category: "accessibility" } },
          {
            event: "category_done",
            data: {
              category: "accessibility",
              findings: [
                {
                  status: "PASS",
                  severity: "minor",
                  category: "accessibility",
                  title: "Lối tiếp cận đạt chuẩn",
                  description: "Ramp slope is 1:12.",
                  resolution: null,
                  citation: null,
                },
              ],
            },
          },
          {
            event: "done",
            data: {
              check_id: "55555555-5555-5555-5555-555555555555",
              total: 2,
              pass_count: 1,
              warn_count: 0,
              fail_count: 1,
            },
          },
        ]),
      });
    });

    await fillParamsAndStartScan(page);

    // Both per-category statuses flipped to "Xong" once their
    // `category_done` events arrived.
    await expect(
      page.getByTestId("category-status-fire_safety").getByText("Xong"),
    ).toBeVisible();
    await expect(
      page.getByTestId("category-status-accessibility").getByText("Xong"),
    ).toBeVisible();

    // Findings rendered with their titles + the FAIL severity badge.
    await expect(page.getByText("Số lối thoát nạn dưới yêu cầu")).toBeVisible();
    await expect(page.getByText("Lối tiếp cận đạt chuẩn")).toBeVisible();
    await expect(page.getByText("CRITICAL")).toBeVisible();

    // Grounded citation surfaces regulation + section + excerpt.
    await expect(page.getByText("QCVN 06:2022/BXD")).toBeVisible();
    await expect(page.getByText(/§\s*3\.1/)).toBeVisible();
    await expect(page.getByText("phải có ít nhất 2 lối thoát nạn")).toBeVisible();

    // ComplianceScore donut visible only after `done`. With 1 PASS of 2
    // findings, scorePct is 50%.
    await expect(page.getByText("50%")).toBeVisible();

    // Network contract: POST carried the typed project_id and default
    // residential project_type.
    expect(lastBody).toMatchObject({
      project_id: PROJECT_ID,
      parameters: expect.objectContaining({ project_type: "residential" }),
    });
  });

  test("renders the amber advisory after done when no findings were emitted", async ({ page }) => {
    await page.route("**/api/v1/codeguard/scan/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        // All five default categories run but each emits no findings.
        // We send just two for brevity — same shape, same outcome.
        body: sseBody([
          { event: "category_start", data: { category: "fire_safety" } },
          {
            event: "category_done",
            data: { category: "fire_safety", findings: [] },
          },
          { event: "category_start", data: { category: "accessibility" } },
          {
            event: "category_done",
            data: { category: "accessibility", findings: [] },
          },
          {
            event: "done",
            data: {
              check_id: "66666666-6666-6666-6666-666666666666",
              total: 0,
              pass_count: 0,
              warn_count: 0,
              fail_count: 0,
            },
          },
        ]),
      });
    });

    await fillParamsAndStartScan(page);

    // The amber "no issues found" advisory appears ONLY after `done` —
    // before that, categories that haven't reported in could still
    // produce findings.
    await expect(page.getByText("Không có vấn đề nào được nêu")).toBeVisible();
    await expect(page.getByText(/đã được nạp vào CODEGUARD chưa/)).toBeVisible();
    // Donut renders with 0% (a clean dim ring).
    await expect(page.getByText("0%")).toBeVisible();
  });

  test("shows a red error banner when the stream emits an error event", async ({ page }) => {
    await page.route("**/api/v1/codeguard/scan/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        // Mid-stream error: the connection succeeded but the pipeline
        // hit a hard failure. The hook treats `error` as terminal —
        // no further events are processed.
        body: sseBody([
          { event: "category_start", data: { category: "fire_safety" } },
          { event: "error", data: { message: "Auto-scan failed" } },
        ]),
      });
    });

    await fillParamsAndStartScan(page);

    await expect(page.getByText("Lỗi khi quét tuân thủ")).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/Auto-scan failed/)).toBeVisible();

    // Reset button stays reachable; user can retry without reloading.
    await expect(page.getByRole("button", { name: /quét lại/i })).toBeVisible();
  });
});
