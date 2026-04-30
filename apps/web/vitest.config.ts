import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * Vitest config for `@aec/web` library-level tests.
 *
 * Scope is deliberately narrow: pure-function helpers in `lib/` (api fetch
 * wrappers, URL builders, validators). Anything that depends on Next's
 * router, server components, or the React render tree goes through the
 * Playwright lane in `tests/e2e/` instead — Vitest in jsdom can't model
 * Next's request scope (cookies(), headers(), middleware) faithfully.
 */
export default defineConfig({
  resolve: {
    alias: {
      // Mirror the `@/*` import alias from tsconfig.json so test files
      // can `import { apiFetch } from "@/lib/api"` the same way the
      // production code does. Without this, Vitest can't resolve `@/`.
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["**/__tests__/**/*.test.{ts,tsx}"],
    // Don't pick up the Playwright suite — those run via `playwright test`.
    exclude: ["tests/e2e/**", "node_modules/**", ".next/**"],
  },
});
