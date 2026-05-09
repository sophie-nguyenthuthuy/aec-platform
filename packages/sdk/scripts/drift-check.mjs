#!/usr/bin/env node
/**
 * SDK drift check.
 *
 * Re-generates `src/generated.ts` from the committed OpenAPI snapshot
 * (`apps/api/tests/openapi.snapshot.json`), diffs against the
 * committed `src/generated.ts`, and exits non-zero if they differ.
 *
 * Why this matters: the SDK is the partner-facing interface. The
 * OpenAPI snapshot is the canonical contract. If a backend route or
 * schema changes without re-running the generator, partners' typed
 * client gets stale — they upgrade to a newer SDK and discover at
 * runtime that the method signature lies. Catching the drift in CI
 * forces the regen step into the same PR as the route change.
 *
 * Implementation: spawn the existing `generate.mjs` against the
 * snapshot file, redirect output to a tempfile, then `diff` it
 * against the committed `generated.ts`. Any difference is a fail.
 *
 * The generator already supports file:// + bare paths as input
 * (see scripts/generate.mjs::loadSpec) so we just point it at the
 * snapshot.
 */

import { readFileSync, writeFileSync, mkdtempSync, copyFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const REPO_ROOT = resolve(__dirname, "../../..");
const SNAPSHOT = resolve(REPO_ROOT, "apps/api/tests/openapi.snapshot.json");
const GENERATED = resolve(__dirname, "../src/generated.ts");
const GENERATOR = resolve(__dirname, "generate.mjs");

// Stash the committed file, regenerate from the snapshot, diff, restore.
// Doing this in-place (rather than redirecting the generator's output
// to a tempfile) sidesteps the generator's hardcoded OUT_FILE path.
// The committed file is restored at the end whether the diff matches
// or not — drift-check should never modify the working tree.
const tmpDir = mkdtempSync(resolve(tmpdir(), "aec-sdk-drift-"));
const stashed = resolve(tmpDir, "generated.committed.ts");
copyFileSync(GENERATED, stashed);

try {
  // Regenerate. Generator picks up the snapshot path from
  // AEC_OPENAPI_URL — pass an absolute path (which the generator's
  // `loadSpec` recognises by the leading `/`) so the working
  // directory the script is invoked from doesn't matter.
  const gen = spawnSync(
    "node",
    [GENERATOR],
    {
      env: { ...process.env, AEC_OPENAPI_URL: SNAPSHOT },
      stdio: "inherit",
    },
  );
  if (gen.status !== 0) {
    console.error("drift-check: generator exited non-zero — see logs above");
    process.exit(gen.status ?? 1);
  }

  const fresh = readFileSync(GENERATED, "utf8");
  const committed = readFileSync(stashed, "utf8");

  if (fresh === committed) {
    console.log("✓ SDK matches the committed OpenAPI snapshot.");
    process.exit(0);
  }

  // Drift. Restore the committed file and emit a diff hint.
  console.error("");
  console.error("✗ SDK drift detected.");
  console.error("");
  console.error("`packages/sdk/src/generated.ts` does not match what the");
  console.error("generator produces from the committed OpenAPI snapshot at");
  console.error(`  ${SNAPSHOT}`);
  console.error("");
  console.error("Most likely cause: a route signature changed in the API,");
  console.error("the OpenAPI snapshot was regenerated, but the SDK wasn't.");
  console.error("");
  console.error("Fix:");
  console.error("  AEC_OPENAPI_URL=apps/api/tests/openapi.snapshot.json \\");
  console.error("    node packages/sdk/scripts/generate.mjs");
  console.error("");
  console.error("Then commit the updated `packages/sdk/src/generated.ts`.");
  process.exit(1);
} finally {
  // Always restore the committed file — drift-check is read-only.
  // Without this, a CI failure would leave the regenerated file in
  // the workspace and a follow-up `git status` would mislead.
  writeFileSync(GENERATED, readFileSync(stashed, "utf8"));
}
