#!/usr/bin/env node
/**
 * Test runtime budget ratchet.
 *
 * Runs the api unit lane with `--durations=0 --durations-min=0.5`,
 * parses pytest's per-test timing report, counts tests that exceed
 * the 500ms budget, compares against `test-runtime-baseline.json`.
 *
 * Why ratchet rather than strict equality
 * ---------------------------------------
 * A handful of tests legitimately take >500ms — integration-tier
 * scaffolding, hypothesis sweeps with high `max_examples`, the
 * full-suite-mounting envelope contract test that walks every
 * router. Driving every test under 500ms would force per-test
 * exemptions; the ratchet says "don't ADD new slow tests" without
 * locking the team into a hard floor.
 *
 * Why 500ms
 * ---------
 * Unit tests run sequentially in the test suite (no xdist by
 * default). At 700+ tests, every 500ms over budget becomes 6 minutes
 * of CI feedback delay over a year. 500ms is the tightest threshold
 * that still tolerates legitimate setup/teardown costs (FastAPI app
 * mount, sqlalchemy engine init).
 *
 * Usage
 * -----
 *   node scripts/check-test-runtime-budget.mjs           # check
 *   node scripts/check-test-runtime-budget.mjs --update  # rewrite baseline
 *
 * Wired as `make test-api-runtime-budget`.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE_PATH = resolve(ROOT, "test-runtime-baseline.json");

// Tests slower than this are "over budget."
const BUDGET_SECONDS = 0.5;

function runPytestWithDurations() {
  // `--durations=0 --durations-min=0.5` shows every test that took
  // ≥0.5s (no upper limit). `-q` keeps non-test output minimal.
  // We tolerate non-zero exit because failing tests are surfaced
  // separately by the rest of the suite — the runtime audit's job
  // is purely to count slow ones.
  let stdout = "";
  try {
    stdout = execSync(
      "pytest --durations=0 --durations-min=0.5 -q --no-header",
      {
        cwd: resolve(ROOT, "apps/api"),
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "ignore"],
        // Pytest can take a couple of minutes; no per-process timeout
        // at the script level — CI's job timeout is the backstop.
      },
    );
  } catch (err) {
    stdout = err.stdout?.toString() ?? "";
    if (!stdout) {
      console.error("pytest produced no output — check `cd apps/api && pytest` directly");
      process.exit(2);
    }
  }
  return stdout;
}

function parseSlowTests(output) {
  // Pytest's durations section looks like:
  //   ============= slowest durations =============
  //   1.23s call     tests/test_x.py::test_y
  //   0.85s setup    tests/test_x.py::test_y
  //   ...
  // We only count `call` lines (setup/teardown duplicates skew the
  // signal — a slow `call` is the test's own runtime, which is what
  // the budget targets).
  const lines = output.split("\n");
  const slow = [];
  let inDurationsSection = false;
  for (const line of lines) {
    if (/slowest \d* durations/.test(line) || line.includes("slowest durations")) {
      inDurationsSection = true;
      continue;
    }
    if (!inDurationsSection) continue;
    // Stop at the next horizontal-rule (===) section.
    if (/^={3,}/.test(line) && !line.includes("durations")) break;

    const m = line.match(/^(\d+\.\d+)s\s+call\s+(.+)$/);
    if (m) {
      const seconds = parseFloat(m[1]);
      if (seconds >= BUDGET_SECONDS) {
        slow.push({ seconds, name: m[2].trim() });
      }
    }
  }
  return slow;
}

function main() {
  let baseline;
  try {
    baseline = JSON.parse(readFileSync(BASELINE_PATH, "utf-8"));
  } catch {
    baseline = { "//": "first run; populated on --update", over_budget_count: 0 };
  }

  console.error("Running pytest with --durations report (this can take ~30s)…");
  const output = runPytestWithDurations();
  const slow = parseSlowTests(output);
  const actual = slow.length;

  const update = process.argv.includes("--update");
  if (update) {
    const next = {
      "//":
        baseline["//"] ||
        `Test runtime budget baseline. Counts unit-lane tests that exceed ${BUDGET_SECONDS}s.`,
      over_budget_count: actual,
      // Surface the worst offenders for review when the baseline
      // gets updated. Sorted desc.
      worst_offenders: slow
        .sort((a, b) => b.seconds - a.seconds)
        .slice(0, 10)
        .map((t) => `${t.seconds.toFixed(2)}s ${t.name}`),
    };
    writeFileSync(BASELINE_PATH, JSON.stringify(next, null, 2) + "\n", "utf-8");
    console.log(
      `Baseline updated: over_budget_count ${baseline.over_budget_count ?? 0} → ${actual}`,
    );
    return;
  }

  const expected = baseline.over_budget_count ?? 0;
  if (actual === expected) {
    console.log(`test runtime budget OK — ${actual} test(s) over ${BUDGET_SECONDS}s, matches baseline.`);
    return;
  }
  if (actual > expected) {
    console.error(
      `\n❌ ${actual - expected} new slow test(s) over the ${BUDGET_SECONDS}s budget ` +
        `(total now ${actual}, baseline ${expected}).\n\n` +
        `Worst offenders:\n` +
        slow
          .sort((a, b) => b.seconds - a.seconds)
          .slice(0, 10)
          .map((t) => `   ${t.seconds.toFixed(2)}s  ${t.name}`)
          .join("\n") +
        `\n\nProfile the new slow test(s):\n` +
        `  cd apps/api && pytest <path>::<name> --durations=0 -v\n\n` +
        `If the slowness is legitimate (integration scaffolding, hypothesis sweep), ` +
        `bump the baseline:\n` +
        `  node scripts/check-test-runtime-budget.mjs --update\n` +
        `…and commit ${BASELINE_PATH.replace(ROOT + "/", "")} alongside the slow test in the same PR.`,
    );
    process.exit(1);
  }
  // actual < expected → reductions celebrate + prompt baseline update.
  console.error(
    `\n🎉 Test runtime budget improved — ${expected - actual} test(s) ` +
      `dropped under the ${BUDGET_SECONDS}s budget (now ${actual}, was ${expected}).\n\n` +
      `Update the baseline:\n` +
      `  node scripts/check-test-runtime-budget.mjs --update\n\n` +
      `…and commit ${BASELINE_PATH.replace(ROOT + "/", "")} so future ` +
      `regressions can't silently rebuild back up.`,
  );
  process.exit(1);
}

main();
