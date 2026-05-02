#!/usr/bin/env node
/**
 * Bundle-size guard for `apps/web`.
 *
 * Walks `.next/static/{chunks,css}` (the assets actually shipped to
 * clients), sums up their byte size, and compares against
 * `apps/web/.bundle-baseline.json`. Fails CI if any tracked metric
 * exceeds the baseline by more than `THRESHOLD_PCT`.
 *
 * Usage
 * -----
 *   node scripts/check-bundle-size.mjs           # check, fail on regression
 *   node scripts/check-bundle-size.mjs --update  # rewrite the baseline
 *
 * Why total bytes (not gzipped)
 * -----------------------------
 * Cheap, deterministic, no extra deps. Gzipped numbers depend on the
 * compression-level of whatever tool happens to be invoked, which
 * makes baselines flaky between local + CI. Total bytes overstates a
 * bit but that's an acceptable trade for the guard not flapping.
 *
 * What the threshold catches
 * --------------------------
 * The 10% bump is the kind of regression that lands when someone
 * pulls in a heavy library by accident (e.g. importing
 * `lodash` instead of `lodash-es`, or pulling all of moment when only
 * `format` was needed). Smaller real-feature drift just bumps the
 * baseline via `--update`.
 */

import { readFileSync, writeFileSync, statSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_ROOT = join(__dirname, "..");
const BASELINE_FILE = join(APP_ROOT, ".bundle-baseline.json");
const STATIC_DIR = join(APP_ROOT, ".next", "static");

// Tracked sections of `.next/static/`. We don't sum the whole dir
// because Next includes per-build hashes in `media/` etc. that aren't
// meaningful client cost.
const TRACKED = ["chunks", "css"];

// Hard limit before failing. 10% picks a balance between "catches
// real regressions" and "doesn't flap on every Tailwind class
// reorder". Tighten once the baseline is solid.
const THRESHOLD_PCT = 10;

function dirSizeBytes(path) {
  let total = 0;
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    const full = join(path, entry.name);
    if (entry.isDirectory()) {
      total += dirSizeBytes(full);
    } else if (entry.isFile()) {
      total += statSync(full).size;
    }
  }
  return total;
}

function measure() {
  const sections = {};
  let total = 0;
  for (const section of TRACKED) {
    const path = join(STATIC_DIR, section);
    let size = 0;
    try {
      size = dirSizeBytes(path);
    } catch (err) {
      if (err.code === "ENOENT") {
        // chunks always exists after a successful build; css can be
        // empty on pages with no <style jsx>. Treat missing as 0.
        size = 0;
      } else {
        throw err;
      }
    }
    sections[section] = size;
    total += size;
  }
  return { sections, total };
}

function fmtKB(bytes) {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function pctDelta(current, baseline) {
  if (baseline === 0) return current === 0 ? 0 : Infinity;
  return ((current - baseline) / baseline) * 100;
}

const args = process.argv.slice(2);
const isUpdate = args.includes("--update");

const current = measure();

if (isUpdate) {
  const out = {
    ...current,
    updated_at: new Date().toISOString(),
    note:
      "Baseline for `apps/web` JS+CSS bundle size. Regenerate with " +
      "`pnpm --filter @aec/web bundle:update` after an intentional " +
      "size change.",
  };
  writeFileSync(BASELINE_FILE, JSON.stringify(out, null, 2) + "\n", "utf8");
  console.log(`✓ Wrote baseline: ${fmtKB(current.total)} total`);
  for (const [section, size] of Object.entries(current.sections)) {
    console.log(`    ${section}: ${fmtKB(size)}`);
  }
  process.exit(0);
}

let baseline;
try {
  baseline = JSON.parse(readFileSync(BASELINE_FILE, "utf8"));
} catch (err) {
  if (err.code === "ENOENT") {
    console.error(
      `::error::No baseline found at ${BASELINE_FILE}. ` +
        `Run \`pnpm --filter @aec/web bundle:update\` to write one.`,
    );
    process.exit(1);
  }
  throw err;
}

let failed = false;
console.log("Bundle size check:");
console.log(`  Total: ${fmtKB(current.total)} (baseline ${fmtKB(baseline.total)})`);

for (const section of TRACKED) {
  const cur = current.sections[section] ?? 0;
  const base = baseline.sections?.[section] ?? 0;
  const delta = pctDelta(cur, base);
  const sign = delta >= 0 ? "+" : "";
  const status = delta > THRESHOLD_PCT ? "✗" : "✓";
  console.log(
    `  ${status} ${section.padEnd(8)} ${fmtKB(cur).padEnd(12)} ` +
      `(baseline ${fmtKB(base)}, ${sign}${delta.toFixed(1)}%)`,
  );
  if (delta > THRESHOLD_PCT) {
    failed = true;
    console.error(
      `::error::Bundle section '${section}' grew by ${delta.toFixed(1)}% ` +
        `(threshold ${THRESHOLD_PCT}%). Investigate the pull-in or ` +
        `bump the baseline via \`pnpm --filter @aec/web bundle:update\`.`,
    );
  }
}

const totalDelta = pctDelta(current.total, baseline.total);
if (totalDelta > THRESHOLD_PCT) {
  failed = true;
  console.error(
    `::error::Total bundle grew by ${totalDelta.toFixed(1)}% ` +
      `(threshold ${THRESHOLD_PCT}%).`,
  );
}

if (failed) {
  process.exit(1);
}
console.log("\n✓ All sections within threshold.");
