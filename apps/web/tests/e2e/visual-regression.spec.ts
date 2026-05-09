import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Visual regression sweep — Playwright `toHaveScreenshot()` on five
 * critical pages.
 *
 * What this catches that other suites don't
 * -----------------------------------------
 * The bundle-size guard catches "did the JS bundle balloon." The
 * a11y sweep catches "is the rendered DOM accessible." The runtime
 * unit + E2E suites catch "do the buttons still work." NONE of them
 * catch:
 *
 *   * A Tailwind upgrade that subtly shifts the spacing scale.
 *   * A design-system token rename that drops half the borders.
 *   * A font swap that re-flows headings, breaking truncation.
 *   * A CSS regression that hides a critical CTA at 1280×720.
 *
 * Visual diff catches all four. The cost is well-understood:
 * baselines are platform-sensitive (macOS antialiasing ≠ Linux CI
 * antialiasing), so the snapshots must be generated on the same OS
 * as the CI runner and committed from there. The workflow:
 *
 *   1. PR runs CI → first run with no baseline writes the baseline
 *      and fails (Playwright's default behaviour).
 *   2. Developer downloads the baseline artifact, commits it under
 *      `__screenshots__/`, pushes again.
 *   3. Subsequent runs diff against the committed baseline. CI fails
 *      on diff above tolerance.
 *
 * Updating baselines after an intentional UI change:
 *   pnpm --filter @aec/web test:e2e -- --update-snapshots
 *
 * Tolerance config
 * ----------------
 * `maxDiffPixelRatio: 0.01` allows up to 1% of pixels to differ —
 * enough to absorb antialiasing jitter at chunk boundaries while
 * still catching meaningful layout shifts. Tighten in lockstep with
 * how stable each baseline turns out to be. Per-page overrides go
 * inline via the second argument to `toHaveScreenshot`.
 *
 * What we explicitly mask
 * -----------------------
 * Any element whose content is intrinsically non-deterministic
 * across runs — primarily timestamps and randomly-generated UUIDs.
 * Without masking, Playwright would surface every relative-time
 * shift ("2 minutes ago" → "3 minutes ago") as a visual diff.
 */

// Default config for every screenshot in this file. Per-test
// overrides can tighten / loosen via the second arg.
const SHOT_OPTS = {
  // 1% pixel-diff budget — absorbs antialiasing jitter at the
  // boundary between regions of solid colour without permitting
  // a meaningful layout shift to slip through.
  maxDiffPixelRatio: 0.01,
  // Animation suppression — prevents shadow easing / focus-ring
  // transitions from flaking depending on when the screenshot
  // fires relative to a paint frame.
  animations: "disabled",
  // Hide the caret so a focused input doesn't blink between runs.
  caret: "hide",
  // Use full-page so the viewport size doesn't decide what's in
  // frame — large pages still get the whole layout pinned.
  fullPage: true,
} as const;

async function freezeTime(page: Page): Promise<void> {
  // Pin Date.now to a fixed instant so any "X minutes ago" /
  // "Updated at HH:MM" rendering is deterministic. Inserts BEFORE
  // any page script runs so even module-init reads see the frozen
  // value.
  await page.addInitScript(() => {
    const FROZEN = new Date("2026-05-03T12:00:00Z").getTime();
    const RealDate = Date;
    // @ts-expect-error - intentional global override for test determinism
    globalThis.Date = class extends RealDate {
      constructor(...args: unknown[]) {
        if (args.length === 0) {
          super(FROZEN);
        } else {
          // @ts-expect-error - forwarding variadic args to the real Date
          super(...args);
        }
      }
      static override now() {
        return FROZEN;
      }
    };
  });
}

test.describe("visual regression", () => {
  test.beforeEach(async ({ page }) => {
    await freezeTime(page);
  });

  test("/projects (hub)", async ({ page }) => {
    await page.route("**/api/v1/projects*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [
            {
              id: "p1",
              organization_id: "00000000-0000-0000-0000-000000000000",
              name: "Marina Tower",
              type: "commercial",
              status: "construction",
              budget_vnd: 12_500_000_000,
              area_sqm: 8500,
              floors: 22,
              address: { city: "HCMC" },
              start_date: "2026-01-01",
              end_date: "2027-06-30",
              metadata: {},
              created_at: "2026-01-01T00:00:00Z",
            },
            {
              id: "p2",
              organization_id: "00000000-0000-0000-0000-000000000000",
              name: "Riverside Office",
              type: "commercial",
              status: "design",
              budget_vnd: 4_200_000_000,
              area_sqm: 3000,
              floors: 8,
              address: { city: "Hanoi" },
              start_date: "2026-03-01",
              end_date: "2026-12-15",
              metadata: {},
              created_at: "2026-02-15T00:00:00Z",
            },
          ],
          meta: { page: 1, per_page: 20, total: 2 },
          errors: null,
        }),
      });
    });

    await page.goto("/projects");
    await expect(page.getByText("Marina Tower")).toBeVisible();
    // Mask any element that surfaces a relative timestamp — the
    // freezeTime helper covers `new Date()` paths but third-party
    // libs sometimes use `performance.now()` for "X seconds ago".
    await expect(page).toHaveScreenshot("projects-hub.png", {
      ...SHOT_OPTS,
      mask: [page.locator("[data-relative-time]")],
    });
  });

  test("/drawbridge/documents (empty state)", async ({ page }) => {
    await page.route(
      "**/api/v1/drawbridge/documents*",
      async (route: Route) => {
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
      },
    );

    await page.goto("/drawbridge/documents");
    await expect(page.getByText(/0 tài liệu/i)).toBeVisible();
    await expect(page).toHaveScreenshot("drawbridge-documents-empty.png", SHOT_OPTS);
  });

  test("/winwork (proposals list, empty)", async ({ page }) => {
    await page.route("**/api/v1/winwork/proposals*", async (route: Route) => {
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

    await page.goto("/winwork");
    await expect(page.getByText(/no proposals yet/i)).toBeVisible();
    await expect(page).toHaveScreenshot("winwork-empty.png", SHOT_OPTS);
  });

  test("/costpulse/prices (empty state)", async ({ page }) => {
    await page.route("**/api/v1/costpulse/**", async (route: Route) => {
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

    await page.goto("/costpulse/prices");
    await expect(
      page.getByRole("heading", { name: /price database/i }),
    ).toBeVisible();
    await expect(page).toHaveScreenshot("costpulse-prices-empty.png", SHOT_OPTS);
  });

  test("/handover (packages list, empty)", async ({ page }) => {
    await page.route("**/api/v1/handover/packages*", async (route: Route) => {
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

    await page.goto("/handover");
    await expect(
      page.getByRole("heading", { name: /gói bàn giao/i }),
    ).toBeVisible();
    await expect(page).toHaveScreenshot("handover-empty.png", SHOT_OPTS);
  });
});
