import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for `@aec/web` E2E tests.
 *
 * Tests intercept API calls with `page.route()` — no running API backend
 * required. The `webServer` block boots `next dev` once per test run so
 * `npm run test:e2e` works out of the box locally and in CI.
 *
 * Pin `NEXT_PUBLIC_API_URL` to a stable fake origin so the route glob we
 * use in tests (`**\/api/v1/pulse/**`) matches regardless of whatever's
 * in the dev shell env.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3101",
    trace: "on-first-retry",
    actionTimeout: 10_000,
  },
  projects: [
    {
      name: "chromium",
      // `channel: "chromium"` picks the full Chromium build that ships with
      // Playwright (installed at ~/Library/Caches/ms-playwright/chromium-*)
      // instead of the smaller `chrome-headless-shell` variant that `Desktop
      // Chrome` would otherwise pull in. Keeps the install footprint to a
      // single browser and works offline once installed.
      use: { ...devices["Desktop Chrome"], channel: "chromium" },
    },
  ],
  webServer: {
    // Use 3101 rather than the obvious 3100 — `re-dagster` (an unrelated local
    // Docker container) already binds 3100 on this workstation, and
    // `reuseExistingServer: true` would happily attach to the wrong app.
    command: "npm run dev -- --port 3101",
    url: "http://127.0.0.1:3101",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    env: {
      NEXT_PUBLIC_API_URL: "http://api.e2e.local",
      // Skip the Supabase auth gate (`apps/web/middleware.ts`). Specs mock
      // every `/api/v1/...` call via `page.route` and never talk to a real
      // Supabase, so providing real env would just slow startup and pull in
      // a network roundtrip per page load. Production code never sets this.
      E2E_BYPASS_AUTH: "1",
    },
  },
});
