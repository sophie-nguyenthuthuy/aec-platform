#!/usr/bin/env node
/**
 * TypeScript strict-mode escape ratchet.
 *
 * Counts occurrences of `@ts-ignore`, `@ts-expect-error`, `as any`,
 * `as unknown as`, and `: any` across the TS codebase
 * (`apps/web` + `packages/ui` + `packages/types`). Each is a
 * documented type-safety hole — comment-based ones suppress the
 * type checker; cast-based ones launder a value through any/unknown
 * to bypass shape checking.
 *
 * Why a ratchet
 * -------------
 * A handful of legitimate escape hatches exist (test-fixture
 * setup, narrow casts at framework boundaries, Date overrides for
 * deterministic test rendering). Strict-equality at zero would
 * force allowlist machinery for those; a ratchet lets the team
 * keep what's there + pin "no NEW ones added without justification."
 *
 * Per-category counts (not just total) so a PR that fixes 2
 * `@ts-ignore` and adds 2 `as any` doesn't net-zero through.
 *
 * Usage
 * -----
 *   node scripts/check-ts-escapes-baseline.mjs           # check
 *   node scripts/check-ts-escapes-baseline.mjs --update  # rewrite baseline
 *
 * Wired into `make test-web-ts-strict`.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE_PATH = resolve(ROOT, "ts-escapes-baseline.json");

// Each pattern → category. We grep with literal strings (not
// regex) for grep-portability across BSD/GNU and to avoid escape-
// hell in the patterns themselves. The result is post-filtered to
// drop legitimate non-matches (e.g. the literal string "@ts-ignore"
// inside a comment that's documenting the rule itself).
//
// `@ts-expect-error` is intentionally NOT in this set. It's a
// different shape from the other escapes:
//   * `@ts-ignore` silently suppresses any error on the line.
//   * `as any` / `as unknown as` widen types with no runtime check.
//   * `@ts-expect-error` REQUIRES the line to have a TS error —
//     when the underlying issue is fixed, the directive itself
//     becomes a TS error and forces the developer to remove it.
//     That's strictly safer than no suppression at all in the
//     cases where suppression is genuinely needed (typing gaps in
//     a third-party lib, narrow test-fixture overrides).
// We track the more-dangerous three; `@ts-expect-error` is allowed
// without ratchet.
const PATTERNS = {
  ts_ignore: "@ts-ignore",
  as_any: "as any",
  as_unknown_as: "as unknown as",
};

// File globs we scan. Tests count separately from source — a test
// file legitimately has more escape-hatch latitude (mocking,
// fixture rigging) than source code.
const SCAN_DIRS = ["apps/web", "packages/ui", "packages/types"];

function countPattern(label, pattern) {
  // Use grep -r with --include for both .ts and .tsx; --exclude-dir
  // for node_modules + build dirs. Returns hit count.
  const args = [
    "-r",
    "--include=*.ts",
    "--include=*.tsx",
    "--exclude-dir=node_modules",
    "--exclude-dir=.next",
    "--exclude-dir=dist",
    "--exclude-dir=build",
    "-F",
    pattern,
    ...SCAN_DIRS,
  ];
  let out = "";
  try {
    out = execSync(
      `grep ${args.map((a) => `'${a.replace(/'/g, "'\\''")}'`).join(" ")}`,
      { cwd: ROOT, encoding: "utf-8", stdio: ["ignore", "pipe", "ignore"] },
    );
  } catch (err) {
    // grep exits 1 on no matches — that's not an error here.
    out = err.stdout?.toString() ?? "";
  }
  if (!out.trim()) return 0;
  return out
    .split("\n")
    .filter((line) => {
      if (!line) return false;
      // Drop self-references in this script's own files (the audit
      // doc + baseline). The patterns match because we WRITE them
      // here for the user to read; that's not a real escape hatch.
      if (line.includes("scripts/check-ts-escapes-baseline.mjs")) return false;
      if (line.includes("ts-escapes-baseline.json")) return false;
      return true;
    }).length;
}

function countAll() {
  const out = {};
  for (const [label, pattern] of Object.entries(PATTERNS)) {
    out[label] = countPattern(label, pattern);
  }
  return out;
}

function main() {
  const baseline = JSON.parse(readFileSync(BASELINE_PATH, "utf-8"));
  const actual = countAll();

  if (process.argv.includes("--update")) {
    const next = { "//": baseline["//"], ...actual };
    writeFileSync(BASELINE_PATH, JSON.stringify(next, null, 2) + "\n", "utf-8");
    console.log("Baseline updated:");
    for (const k of Object.keys(PATTERNS)) {
      console.log(`  ${k}: ${baseline[k] ?? 0} → ${actual[k]}`);
    }
    return;
  }

  const ups = [];
  const downs = [];
  for (const k of Object.keys(PATTERNS)) {
    const exp = baseline[k] ?? 0;
    const got = actual[k];
    if (got > exp) ups.push({ k, from: exp, to: got });
    else if (got < exp) downs.push({ k, from: exp, to: got });
  }

  if (ups.length === 0 && downs.length === 0) {
    console.log("ts-escapes baseline OK — no drift.");
    return;
  }
  if (ups.length) {
    console.error("\n❌ New TS strict-mode escape hatches:");
    for (const d of ups) {
      console.error(`   ${d.k}: ${d.from} → ${d.to}  (+${d.to - d.from})`);
    }
    console.error(
      "\nFix the new escapes (each is a real type hole) OR explicitly bump " +
        "the baseline if the increase is intentional. `as unknown as Foo` " +
        "is sometimes legitimate at framework boundaries; `@ts-ignore` " +
        "rarely is — prefer `@ts-expect-error` so the suppression " +
        "fails-loud when the underlying issue is fixed.",
    );
  }
  if (downs.length) {
    console.error("\n🎉 TS escape-hatch reductions:");
    for (const d of downs) {
      console.error(`   ${d.k}: ${d.from} → ${d.to}  (-${d.from - d.to})`);
    }
    console.error(
      "\nRun `node scripts/check-ts-escapes-baseline.mjs --update` and " +
        "commit `ts-escapes-baseline.json`.",
    );
  }
  process.exit(1);
}

main();
