import { defineConfig } from "vitest/config";

/**
 * Vitest config for `@aec/sdk` client-core tests.
 *
 * The SDK has two layers:
 *   * `client.ts` — hand-written HTTP core (auth, retry, envelope
 *     unwrap, error shape). Pure logic, no React, no DOM. Node test
 *     environment fits exactly.
 *   * `generated.ts` — auto-generated method table. Tested transitively
 *     by the drift CI gate that regenerates it from the OpenAPI
 *     snapshot and diffs the result; no need to test the generated
 *     glue here.
 *
 * Tests live under `src/__tests__/` co-located with the subject they
 * test, matching the convention in `packages/ui` and `apps/web/lib`.
 */
export default defineConfig({
  test: {
    // node not jsdom — `fetch` is global on node 18+, no DOM needed.
    environment: "node",
    globals: true,
    include: ["src/__tests__/**/*.test.ts"],
  },
});
