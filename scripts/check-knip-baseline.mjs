#!/usr/bin/env node
/**
 * Knip baseline ratchet.
 *
 * Runs `knip --reporter json`, sums findings per category (files,
 * dependencies, exports, types), and compares to `knip-baseline.json`.
 *
 *  - count > baseline → fail (new dead code landed)
 *  - count < baseline → fail with celebratory prompt to lower the
 *                       baseline in the same PR (so future regressions
 *                       can't silently rebuild back up)
 *  - count == baseline → pass
 *
 * Why per-category rather than total
 * ----------------------------------
 * One PR might fix 5 unused exports and accidentally add 5 unused
 * dependencies. Net zero on `total`, but a real regression on
 * `dependencies`. Per-category gates catch each direction.
 *
 * Usage
 * -----
 *   node scripts/check-knip-baseline.mjs           # check
 *   node scripts/check-knip-baseline.mjs --update  # rewrite baseline
 *
 * Wired into `make test-web-deadcode`.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE_PATH = resolve(ROOT, "knip-baseline.json");

const CATEGORIES = ["files", "dependencies", "exports", "types"];

function runKnip() {
  // Knip exits non-zero when it finds issues (the whole point of
  // running it). We want to capture stdout regardless of exit code,
  // so swallow the throw and parse stdout.
  let stdout = "";
  try {
    stdout = execSync("pnpm exec knip --reporter json", {
      cwd: ROOT,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    });
  } catch (err) {
    // err.stdout is the captured stream; knip writes JSON there
    // even on issue-found exits.
    stdout = err.stdout?.toString() ?? "";
    if (!stdout) {
      console.error("knip produced no stdout — check `pnpm exec knip` directly");
      process.exit(2);
    }
  }
  return JSON.parse(stdout);
}

function countByCategory(report) {
  const totals = Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
  // Knip's JSON shape: `{ issues: [{ file, files: [...], exports: [...], ... }, ...] }`
  // where each entry is per-source-file and each category-keyed list
  // contains the unused symbols in that file.
  const issues = report.issues ?? [];
  for (const entry of issues) {
    for (const cat of CATEGORIES) {
      const v = entry[cat];
      if (Array.isArray(v)) totals[cat] += v.length;
    }
  }
  return totals;
}

function main() {
  const baseline = JSON.parse(readFileSync(BASELINE_PATH, "utf-8"));
  const report = runKnip();
  const actual = countByCategory(report);

  const update = process.argv.includes("--update");
  if (update) {
    const next = { "//": baseline["//"], ...actual };
    writeFileSync(BASELINE_PATH, JSON.stringify(next, null, 2) + "\n", "utf-8");
    console.log(`Baseline updated:`);
    for (const c of CATEGORIES) {
      console.log(`  ${c}: ${baseline[c]} → ${actual[c]}`);
    }
    return;
  }

  const drift = [];
  for (const c of CATEGORIES) {
    const exp = baseline[c] ?? 0;
    const got = actual[c] ?? 0;
    if (got > exp) drift.push({ cat: c, dir: "up", from: exp, to: got });
    else if (got < exp) drift.push({ cat: c, dir: "down", from: exp, to: got });
  }

  if (drift.length === 0) {
    console.log("knip baseline OK — no drift.");
    return;
  }

  // Pretty-print + decide exit code. Up-direction always fails.
  // Down-direction also fails (the ratchet "celebratory failure")
  // because we want the developer to commit the new baseline so
  // future regressions can't quietly grow back to the prior level.
  const ups = drift.filter((d) => d.dir === "up");
  const downs = drift.filter((d) => d.dir === "down");

  if (ups.length) {
    console.error("\n❌ New dead-code findings — knip baseline regressed:");
    for (const d of ups) {
      console.error(`   ${d.cat}: ${d.from} → ${d.to}  (+${d.to - d.from})`);
    }
    console.error(
      "\nFix the new findings (run `pnpm exec knip` for the offender list) " +
        "OR explicitly bump the baseline if the increase is intentional " +
        "(e.g. you added a new public-API export reserved for next sprint).",
    );
  }
  if (downs.length) {
    console.error("\n🎉 Dead-code reductions — bump the baseline:");
    for (const d of downs) {
      console.error(`   ${d.cat}: ${d.from} → ${d.to}  (-${d.from - d.to})`);
    }
    console.error(
      "\nRun `node scripts/check-knip-baseline.mjs --update` and commit " +
        "the updated `knip-baseline.json`. Without this, the next PR could " +
        "silently rebuild back to the prior level.",
    );
  }
  process.exit(1);
}

main();
