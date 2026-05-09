import { test, expect, type Route } from "@playwright/test";

/**
 * E2E: load-bearing accessibility attributes across CODEGUARD pages.
 *
 * This spec doesn't run a full axe-core audit (that's a follow-up
 * round once `@axe-core/playwright` is added as a dev dep). It locks
 * in the specific attribute contracts that the manual audit produced
 * — assertions that, if a future refactor accidentally drops, would
 * break screen-reader users without any visible UI change.
 *
 * Each test asserts a single attribute on a single element with a
 * comment explaining the user-visible failure mode it catches. Adding
 * an axe round later wraps these — these stay as the regression
 * guards because axe rules drift between versions.
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

test.describe("CODEGUARD / Accessibility", () => {
  test("query: input has aria-label and streaming answer is aria-live", async ({ page }) => {
    // Failure mode: screen-reader user lands on `/codeguard/query`,
    // tabs to the input — without `aria-label`, the placeholder is
    // announced inconsistently or not at all. The streaming answer
    // container without `aria-live` would silently grow off-screen.
    await page.route("**/api/v1/codeguard/query/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          { event: "token", data: { delta: "Test answer." } },
          {
            event: "done",
            data: {
              answer: "Test answer.",
              confidence: 0.5,
              citations: [],
              related_questions: [],
              check_id: null,
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/query");

    const input = page.getByRole("textbox", { name: /câu hỏi về quy chuẩn/i });
    await expect(input).toBeVisible();
    await input.fill("Test question");
    await page.getByRole("button", { name: /gửi/i }).click();

    // The assistant turn container is `aria-live="polite"` so screen
    // readers announce streamed tokens. `aria-busy` flips during
    // streaming, then settles to false on the terminal `done` event.
    const live = page.locator("[aria-live='polite']").filter({ hasText: "Test answer." });
    await expect(live).toBeVisible();
    await expect(live).toHaveAttribute("aria-busy", "false");
  });

  test("scan: category toggles expose aria-pressed", async ({ page }) => {
    // Failure mode: visually-distinguishable selected/unselected
    // category chips have no accessible state — screen-reader users
    // can't tell which categories are scoped without a checkbox-style
    // semantic.
    await page.goto("/codeguard/scan");
    const fireToggle = page.getByRole("button", { name: "PCCC" });
    // Defaults: every category selected on page load.
    await expect(fireToggle).toHaveAttribute("aria-pressed", "true");

    await fireToggle.click();
    await expect(fireToggle).toHaveAttribute("aria-pressed", "false");

    await fireToggle.click();
    await expect(fireToggle).toHaveAttribute("aria-pressed", "true");
  });

  test("scan: per-category progress strip has aria-live region", async ({ page }) => {
    // Failure mode: scan finishes ~30s of LLM work in five chunks —
    // without `aria-live` on the progress strip, screen readers don't
    // announce the per-category "Xong" transitions, leaving users
    // wondering whether the scan is still running.
    await page.route("**/api/v1/codeguard/scan/stream", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseBody([
          { event: "category_start", data: { category: "fire_safety" } },
          {
            event: "category_done",
            data: { category: "fire_safety", findings: [] },
          },
          {
            event: "done",
            data: {
              check_id: "11111111-1111-1111-1111-111111111111",
              total: 0,
              pass_count: 0,
              warn_count: 0,
              fail_count: 0,
            },
          },
        ]),
      });
    });

    await page.goto("/codeguard/scan");
    await page.getByPlaceholder("UUID").fill("33333333-3333-3333-3333-333333333333");
    await page.getByRole("button", { name: /tiếp tục/i }).click();
    await page.getByRole("button", { name: /bắt đầu quét/i }).click();

    const progress = page.getByRole("region", {
      name: /tiến độ quét theo hạng mục/i,
    });
    await expect(progress).toBeVisible();
    await expect(progress).toHaveAttribute("aria-live", "polite");
  });

  test("regulations: search input + filter select have aria-labels", async ({ page }) => {
    // Failure mode: two adjacent inputs (search + category select)
    // with no visible <label>s. Without `aria-label`, both are
    // announced as just "edit text" / "combobox" — same as every
    // other unlabeled input on the page. The aria-labels disambiguate.
    await page.route("**/api/v1/codeguard/regulations*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
          meta: { page: 1, per_page: 50, total: 0 },
          errors: null,
        }),
      });
    });

    await page.goto("/codeguard/regulations");

    // Search input — RegulationSearch renders `<input type="search"
    // aria-label="Tìm kiếm quy chuẩn">`. `getByRole` picks it up by
    // accessible name only.
    const search = page.getByRole("searchbox", { name: /tìm kiếm quy chuẩn/i });
    await expect(search).toBeVisible();

    // Category filter <select> — `aria-label="Lọc theo hạng mục"`.
    const filter = page.getByRole("combobox", { name: /lọc theo hạng mục/i });
    await expect(filter).toBeVisible();
  });
});
