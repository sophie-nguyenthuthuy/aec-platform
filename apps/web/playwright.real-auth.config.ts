import { defineConfig, devices } from "@playwright/test";

/**
 * Opt-in Playwright lane that exercises the *real* auth flow against a
 * live Supabase project + the local API. Keeps the default e2e gate
 * (mocked, fast) untouched.
 *
 * Run locally:
 *   AEC_REAL_AUTH_EMAIL=dev@aec-platform.vn \
 *   AEC_REAL_AUTH_PASSWORD=DevPassw0rd! \
 *   pnpm --filter @aec/web exec playwright test --config=playwright.real-auth.config.ts
 *
 * CI: only enable once SUPABASE_* + AEC_REAL_AUTH_* secrets are wired.
 */
export default defineConfig({
  testDir: "./tests/e2e-real-auth",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3102",
    trace: "retain-on-failure",
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chromium" },
    },
  ],
  webServer: {
    command: "npm run dev -- --port 3102",
    url: "http://127.0.0.1:3102/login",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    env: {
      // No E2E_BYPASS_AUTH here on purpose — that's the whole point of
      // this lane. The middleware actually validates Supabase cookies.
      NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8002",
      NEXT_PUBLIC_SUPABASE_URL:
        process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://ejoxmgufldlsbmixqjcm.supabase.co",
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:
        process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
        "sb_publishable_PS-udXBaYTqATMkNk0OR3Q_uBwZLc3u",
    },
  },
});
