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
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
    actionTimeout: 10_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev -- --port 3100",
    url: "http://127.0.0.1:3100",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    env: {
      NEXT_PUBLIC_API_URL: "http://api.e2e.local",
    },
  },
});
