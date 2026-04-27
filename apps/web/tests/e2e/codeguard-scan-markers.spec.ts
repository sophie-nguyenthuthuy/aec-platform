import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: inline `[N]` citation markers inside scan finding descriptions.
 *
 * The scan prompt now instructs the model to emit `[1]` markers in the
 * `description` field referring to the finding's own citation (each
 * finding has at most one). The `<FindingItem>` component renders the
 * description with `<AnswerWithCitations>`, which rewrites the marker
 * as a hover-expanded chip — same component the query page uses.
 *
 * Coverage
 * --------
 * 1. A finding whose description contains `[1]` renders a
 *    `<button>` chip; hovering shows the cited regulation + section
 *    + excerpt — same UX as the query page.
 * 2. Findings without a citation (PASS without source) that contain
 *    `[1]` text fall back to literal rendering (no chip pointing at
 *    undefined). Same out-of-range guard as `<AnswerWithCitations>`
 *    on the query path.
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

async function startScan(page: import("@playwright/test").Page) {
  await page.goto("/codeguard/scan");
  await page.getByPlaceholder("UUID").fill(PROJECT_ID);
  await page.getByRole("button", { name: /tiếp tục/i }).click();
  await expect(page.getByRole("button", { name: /bắt đầu quét/i })).toBeVisible();
  await page.getByRole("button", { name: /bắt đầu quét/i }).click();
}

test.describe("CODEGUARD / Scan inline citation markers", () => {
  test("renders [1] in a finding description as a hover chip", async ({ page }) => {
    await page.route("**/api/v1/codeguard/scan/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
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
                  description:
                    "Dự án 6 tầng chỉ có 1 lối thoát nạn, không đạt yêu cầu tối thiểu 2 lối [1].",
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
          {
            event: "done",
            data: {
              check_id: "55555555-5555-5555-5555-555555555555",
              total: 1,
              pass_count: 0,
              warn_count: 0,
              fail_count: 1,
            },
          },
        ]),
      });
    });

    await startScan(page);

    // The marker rendered as an interactive button (not literal text),
    // labelled with the citation summary so screen readers convey it.
    const marker = page.getByRole("button", { name: /Trích dẫn 1:/ });
    await expect(marker).toBeVisible();
    await expect(marker).toHaveText("[1]");

    // Hover surfaces the tooltip — same pattern as the query page.
    await marker.hover();
    const tooltip = page
      .getByRole("tooltip")
      .filter({ hasText: "phải có ít nhất 2 lối thoát nạn" });
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText("QCVN 06:2022/BXD");
    await expect(tooltip).toContainText("3.1");
  });

  test("findings without a citation render [1] as literal text (no broken chip)", async ({ page }) => {
    // Some PASS findings have `citation: null` — but the LLM might
    // still emit a `[1]` marker. The component must NOT render a chip
    // whose tooltip points at undefined; it falls back to literal text.
    await page.route("**/api/v1/codeguard/scan/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
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
                  status: "PASS",
                  severity: "minor",
                  category: "fire_safety",
                  title: "Tổng quan đạt",
                  description:
                    "Tất cả tiêu chí PCCC đã được đáp ứng theo bản vẽ [1].",
                  resolution: null,
                  citation: null,
                },
              ],
            },
          },
          {
            event: "done",
            data: {
              check_id: "66666666-6666-6666-6666-666666666666",
              total: 1,
              pass_count: 1,
              warn_count: 0,
              fail_count: 0,
            },
          },
        ]),
      });
    });

    await startScan(page);

    // Description text contains the literal `[1]` — no chip rendered.
    await expect(
      page.getByText(/Tất cả tiêu chí PCCC đã được đáp ứng theo bản vẽ \[1\]/),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /Trích dẫn 1:/ })).toHaveCount(0);
  });
});
