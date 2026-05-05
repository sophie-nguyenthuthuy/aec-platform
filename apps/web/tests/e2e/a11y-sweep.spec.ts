import AxeBuilder from "@axe-core/playwright";
import { test, expect, type Route, type Page } from "@playwright/test";

/**
 * Accessibility sweep — runs axe-core against the highest-traffic
 * routes in the dashboard. Each route is loaded with stub API data
 * (same `page.route` interception pattern as the per-module specs)
 * so axe sees the real rendered DOM, not a loading skeleton.
 *
 * What we gate on
 * ---------------
 * For now: WCAG 2.1 A + AA tags only. No `--strict` zero-violations
 * gate yet — the goal of this first pass is to *land the
 * infrastructure* and SURFACE the violations. Each route below has a
 * `KNOWN_VIOLATIONS` allowlist of rules we've reviewed and accepted
 * as out-of-scope (e.g. `region` for full-page apps that don't use
 * landmarks the way axe expects). New violations not on the
 * allowlist red-gate the PR.
 *
 * To tighten the gate over time:
 *   1. Fix one of the violations in the allowlist.
 *   2. Remove it from the allowlist for that route.
 *   3. Run the suite — if green, ratchet.
 *
 * To debug a fresh violation, the `attachReport` helper saves the
 * full axe JSON to `test-results/a11y/<route>.json` so the
 * actions/upload-artifact step in CI picks it up.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

// Per-route allowlist. Empty array = "must be zero violations." Non-
// empty = "we've accepted these rule ids as known-not-fixed." Each
// entry should have a comment explaining WHY (otherwise this just
// becomes a way to silence the gate).
//
// Format: { ruleId, reason }
type Allowed = { id: string; reason: string };
type RouteAllowlist = Record<string, Allowed[]>;

const ALLOWLIST: RouteAllowlist = {
  "/projects": [
    // The dashboard pages have a top-level <main> but axe expects
    // *every* meaningful chunk to live inside a landmark. Page-level
    // refactor would touch ~30 files; treat as future work.
    { id: "region", reason: "page-level landmark refactor pending" },
  ],
  "/drawbridge/documents": [
    { id: "region", reason: "page-level landmark refactor pending" },
    // The discipline + doc-type filter <select>s are bare (no <label>
    // wrapper). The visible heading "Tất cả bộ môn" / "Tất cả loại"
    // is a paragraph above them. Worth fixing — tracked as follow-up.
    { id: "select-name", reason: "filter selects need <label>; tracked" },
  ],
  "/winwork": [
    { id: "region", reason: "page-level landmark refactor pending" },
  ],
  "/costpulse/prices": [
    { id: "region", reason: "page-level landmark refactor pending" },
    { id: "select-name", reason: "filter selects need <label>; tracked" },
  ],
  "/handover": [
    { id: "region", reason: "page-level landmark refactor pending" },
  ],
};

async function runAxe(
  page: Page,
  routeKey: string,
  allowed: Allowed[],
): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();

  // Persist the full report — uploaded as a CI artifact for triage.
  // The route key is sanitized so the filename is filesystem-safe.
  const safe = routeKey.replace(/[^a-z0-9]+/gi, "_");
  const dir = join(process.cwd(), "test-results", "a11y");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, `${safe}.json`),
    JSON.stringify(results, null, 2),
    "utf8",
  );

  // Filter out allow-listed rules — anything left is a new
  // violation that fails the test.
  const allowedIds = new Set(allowed.map((a) => a.id));
  const unexpected = results.violations.filter((v) => !allowedIds.has(v.id));

  if (unexpected.length > 0) {
    const summary = unexpected
      .map(
        (v) =>
          `  • [${v.impact}] ${v.id}: ${v.help}\n` +
          `    Affected nodes: ${v.nodes.length}\n` +
          `    Help: ${v.helpUrl}`,
      )
      .join("\n");
    throw new Error(
      `${unexpected.length} unexpected a11y violation(s) on ${routeKey}:\n${summary}\n\n` +
        `If these are intentional, add them to ALLOWLIST in apps/web/tests/e2e/a11y-sweep.spec.ts ` +
        `with a justifying comment.`,
    );
  }
}

// ---- Per-route smoke setups ----
//
// Each block fakes the network for one route, navigates, and runs
// axe. We keep the fakes minimal — just enough to render meaningful
// content (vs. a "loading…" state that axe would scan and pass on
// trivially).

test.describe("a11y sweep", () => {
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
              name: "Test Project",
              type: "commercial",
              status: "construction",
              budget_vnd: 1_000_000_000,
              area_sqm: 500,
              floors: 5,
              address: { city: "HCMC" },
              start_date: "2026-01-01",
              end_date: "2026-12-31",
              metadata: {},
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          meta: { page: 1, per_page: 20, total: 1 },
          errors: null,
        }),
      });
    });

    await page.goto("/projects");
    await expect(page.getByText("Test Project")).toBeVisible();
    await runAxe(page, "/projects", ALLOWLIST["/projects"] ?? []);
  });

  test("/drawbridge/documents", async ({ page }) => {
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
    await runAxe(
      page,
      "/drawbridge/documents",
      ALLOWLIST["/drawbridge/documents"] ?? [],
    );
  });

  test("/winwork (proposals list)", async ({ page }) => {
    await page.route(
      "**/api/v1/winwork/proposals*",
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

    await page.goto("/winwork");
    await expect(page.getByText(/no proposals yet/i)).toBeVisible();
    await runAxe(page, "/winwork", ALLOWLIST["/winwork"] ?? []);
  });

  test("/costpulse/prices", async ({ page }) => {
    await page.route(
      "**/api/v1/costpulse/**",
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

    await page.goto("/costpulse/prices");
    await expect(page.getByRole("heading", { name: /price database/i })).toBeVisible();
    await runAxe(
      page,
      "/costpulse/prices",
      ALLOWLIST["/costpulse/prices"] ?? [],
    );
  });

  test("/handover (packages)", async ({ page }) => {
    await page.route(
      "**/api/v1/handover/packages*",
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

    await page.goto("/handover");
    await expect(page.getByRole("heading", { name: /gói bàn giao/i })).toBeVisible();
    await runAxe(page, "/handover", ALLOWLIST["/handover"] ?? []);
  });
});
