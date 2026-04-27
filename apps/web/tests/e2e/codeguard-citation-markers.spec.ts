import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: inline `[N]` citation markers in CODEGUARD query answers.
 *
 * The LLM is now prompted to emit `[1]`, `[2]` markers inline in the
 * answer text (see `_QA_SYSTEM` in `apps/ml/pipelines/codeguard.py`).
 * The frontend parses those markers and substitutes them with
 * hover-expanded citation chips. This test pins down:
 *
 * 1. Markers in the answer text render as buttons (the `[1]` chip),
 *    not literal `[1]` characters.
 * 2. The hover-tooltip carries the cited regulation + section + excerpt.
 *    We assert visibility via the `role="tooltip"` element rather than
 *    actually mousing over (Playwright's hover assertions are flaky on
 *    CSS-only popovers across runs); presence in the DOM is the
 *    contract that matters here.
 * 3. Out-of-range markers fall back to literal text — `[5]` when only
 *    1 citation exists is rendered as plain `[5]`, not a broken chip.
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

test.describe("CODEGUARD / Inline citation markers", () => {
  test("renders [N] markers as accessible chips with tooltip content", async ({ page }) => {
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "done",
            data: {
              answer:
                "Hành lang thoát nạn rộng tối thiểu 1.4 m [1]. " +
                "Số lối thoát nạn không nhỏ hơn 2 mỗi tầng [2].",
              confidence: 0.9,
              citations: [
                {
                  regulation_id: "11111111-1111-1111-1111-111111111111",
                  regulation: "QCVN 06:2022/BXD",
                  section: "3.2.1",
                  excerpt: "không được nhỏ hơn 1.4 m",
                  source_url: null,
                },
                {
                  regulation_id: "22222222-2222-2222-2222-222222222222",
                  regulation: "QCVN 06:2022/BXD",
                  section: "3.1",
                  excerpt: "phải có ít nhất 2 lối thoát nạn",
                  source_url: null,
                },
              ],
              related_questions: [],
              check_id: "33333333-3333-3333-3333-333333333333",
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Yêu cầu hành lang thoát nạn?");
    await page.getByRole("button", { name: /gửi/i }).click();

    // Each marker renders as a <button> with the bracketed label as its
    // visible text. `getByRole` confirms it's an actual interactive
    // element, not a literal text node.
    const marker1 = page.getByRole("button", { name: /Trích dẫn 1:/ });
    const marker2 = page.getByRole("button", { name: /Trích dẫn 2:/ });
    await expect(marker1).toBeVisible();
    await expect(marker2).toBeVisible();
    await expect(marker1).toHaveText("[1]");
    await expect(marker2).toHaveText("[2]");

    // Tooltips are CSS-hidden until `group-hover` (Tailwind `invisible`
    // → `visible`). Hover the chip and then assert visibility +
    // content — `toContainText` requires the element to be visible.
    await marker1.hover();
    const tooltip1 = page
      .getByRole("tooltip")
      .filter({ hasText: "không được nhỏ hơn 1.4 m" });
    await expect(tooltip1).toBeVisible();
    await expect(tooltip1).toContainText("QCVN 06:2022/BXD");
    await expect(tooltip1).toContainText("3.2.1");

    // Move away then hover the second marker — confirms each chip
    // controls its own popover (no sticky state across hovers).
    await page.mouse.move(0, 0);
    await marker2.hover();
    const tooltip2 = page
      .getByRole("tooltip")
      .filter({ hasText: "phải có ít nhất 2 lối thoát nạn" });
    await expect(tooltip2).toBeVisible();
    await expect(tooltip2).toContainText("3.1");
  });

  test("out-of-range markers fall back to literal text", async ({ page }) => {
    // The LLM mis-numbered: answer has [5] but only 1 citation exists.
    // The component must render [5] as plain text, NOT a broken chip
    // pointing at undefined.
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "done",
            data: {
              answer: "Một câu trả lời với marker sai [5].",
              confidence: 0.5,
              citations: [
                {
                  regulation_id: "11111111-1111-1111-1111-111111111111",
                  regulation: "QCVN",
                  section: "1.1",
                  excerpt: "x",
                  source_url: null,
                },
              ],
              related_questions: [],
              check_id: null,
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Câu hỏi marker sai?");
    await page.getByRole("button", { name: /gửi/i }).click();

    // The literal `[5]` appears as text. There is NO button labelled
    // "Trích dẫn 5" — the parser refused to point at a nonexistent
    // citation.
    await expect(page.getByText("Một câu trả lời với marker sai [5].")).toBeVisible();
    await expect(page.getByRole("button", { name: /Trích dẫn 5:/ })).toHaveCount(0);
  });

  test("plain text without markers passes through unchanged", async ({ page }) => {
    // The prompt instructs the model to emit markers, but for safety we
    // want answers without any `[N]` to render normally — same as
    // before this round. Regression target if the parser ever
    // accidentally consumes brackets it shouldn't.
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          {
            event: "done",
            data: {
              answer: "Câu trả lời không có marker nào.",
              confidence: 0.7,
              citations: [
                {
                  regulation_id: "11111111-1111-1111-1111-111111111111",
                  regulation: "QCVN",
                  section: "1.1",
                  excerpt: "x",
                  source_url: null,
                },
              ],
              related_questions: [],
              check_id: null,
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");
    await page
      .getByPlaceholder(/Đặt câu hỏi về QCVN, TCVN, luật xây dựng/i)
      .fill("Plain text question?");
    await page.getByRole("button", { name: /gửi/i }).click();

    await expect(page.getByText("Câu trả lời không có marker nào.")).toBeVisible();
    // No marker buttons rendered.
    await expect(page.getByRole("button", { name: /Trích dẫn \d+:/ })).toHaveCount(0);
  });
});
