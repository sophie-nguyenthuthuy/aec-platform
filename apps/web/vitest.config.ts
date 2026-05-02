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
  // The repo's tsconfig sets `jsx: "preserve"` because Next handles the
  // transform downstream. Vitest's default esbuild loader honours that
  // and leaves JSX untransformed → ReferenceError: React is not defined
  // at runtime. Force the React 17+ automatic runtime here so test files
  // don't need an explicit `import React from "react"` (which the source
  // components themselves don't have either). Same fix as
  // `packages/ui/vitest.config.ts`.
  esbuild: {
    jsx: "automatic",
  },
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
    // Imports `@testing-library/jest-dom/vitest` so component tests
    // can use `toBeInTheDocument` / `toHaveClass`. See file for scope
    // discussion — TL;DR pure components are OK here, anything router
    // or RSC-dependent goes through Playwright.
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/__tests__/**/*.test.{ts,tsx}"],
    // Don't pick up the Playwright suite — those run via `playwright test`.
    exclude: ["tests/e2e/**", "node_modules/**", ".next/**"],
    coverage: {
      provider: "v8",
      // Restrict measurement to the surfaces Vitest can faithfully cover:
      //   * `lib/`   — pure helpers (api fetch wrappers, validators)
      //   * `hooks/` — TanStack Query wrappers (mockable via global fetch)
      // `app/` is server-component territory + Next router internals,
      // exercised by the Playwright lane only. Including it would skew
      // the % down toward "the framework files we can't unit-test."
      include: ["lib/**/*.{ts,tsx}", "hooks/**/*.{ts,tsx}"],
      exclude: [
        "**/__tests__/**",
        "**/*.config.{ts,tsx}",
        "**/types.ts",
        "**/keys.ts",
        // `lib/supabase-*` calls into next/headers / @supabase/ssr;
        // covered by E2E + the auth-bypass middleware test.
        "lib/supabase-*.ts",
        "lib/supabase-env.ts",
      ],
      reporter: ["text", "html", "json"],
      reportsDirectory: "./coverage",
      // Floor pinned at the current baseline. Raise in lockstep with
      // batches of new hook tests landing — the contract is "don't go
      // down meaningfully", so the floor is current_value - ~1pt to
      // absorb v8 run-to-run jitter.
      //
      // 2026-05-02 (initial bootstrap):  6.79 / 44.07 / 19.54 / 6.79
      // 2026-05-02 round 2 (+5 hooks):  10.62 / 54.64 / 27.92 / 10.62
      // 2026-05-02 round 3 (+5 hooks):  13.49 / 58.85 / 33.13 / 13.49
      thresholds: {
        lines: 12,
        statements: 12,
        functions: 32,
        branches: 57,
      },
    },
  },
});
