import { defineConfig } from "vitest/config";

/**
 * Vitest config for component-level tests in `@aec/ui`.
 *
 * Strategy
 * --------
 * Components in this package are pure presentational React — props in,
 * markup + ARIA roles + event-handler calls out. They have no
 * dependency on Next.js routing, the API client, or TanStack Query.
 * jsdom is sufficient; we don't need a full app server like the
 * Playwright lane does.
 *
 * Test files live alongside their subject under `__tests__/<Name>.test.tsx`.
 * The pattern matches the broader convention in this monorepo (api tests
 * under `apps/api/tests/`, ml tests under `apps/ml/tests/`) — co-locating
 * inside the package keeps the test file's import paths short
 * (`../ConflictCard` not `../../packages/ui/drawbridge/ConflictCard`).
 */
export default defineConfig({
  // The repo's tsconfig sets `jsx: "preserve"` because Next handles the
  // transform downstream. Vitest's default esbuild loader honours that
  // and leaves JSX untransformed → ReferenceError: React is not defined
  // at runtime. Force the React 17+ automatic runtime here so test files
  // don't need an explicit `import React from "react"` (which the source
  // components themselves don't have either).
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.tsx"],
    include: ["**/__tests__/**/*.test.{ts,tsx}"],
    // Tailwind class strings are part of the rendered output but we don't
    // need a real Tailwind compile for assertions on them — string-match
    // on the className attribute is enough. So no PostCSS plugin needed.
    css: false,
    // Coverage: on-demand via `pnpm test:coverage`; not run by default
    // because v8 instrumentation slows the suite ~3x. The threshold is
    // a soft gate today (low number) — bump it as more components get
    // tests. Same staircase pattern we use on apps/api's pytest-cov.
    coverage: {
      provider: "v8",
      // Only the .tsx components we ship — exclude index barrels, types,
      // helper modules, and the test files themselves. `lib/cn.ts` is a
      // 5-line `cn(clsx, twMerge)` helper, exhaustively exercised by
      // every other component test, so listing it isn't useful.
      include: ["**/*.tsx"],
      exclude: [
        "**/__tests__/**",
        "**/*.config.{ts,tsx}",
        "**/vitest.setup.tsx",
        // Recharts wrappers (ProgressChart, GanttBar visual layer): they
        // render against a real-DOM-only canvas API jsdom doesn't model,
        // so unit-coverage understates them. The Playwright lane covers
        // these in their actual usage.
        "**/PriceTrendChart.tsx",
        "**/ProgressChart.tsx",
        "**/GanttChart.tsx",
        "**/PDFViewer.tsx",
      ],
      reporter: ["text", "html", "json"],
      reportsDirectory: "./coverage",
      // Floor pinned at the current baseline (2026-05-01: 7 specs covering
      // 7 of ~50 components, so coverage is intentionally low). The point
      // of pinning is "don't go down" — every batch of new tests should
      // raise these numbers. CI fails the run if any drops below.
      thresholds: {
        lines: 20,
        statements: 20,
        functions: 35,
        branches: 60,
      },
    },
  },
});
