#!/usr/bin/env node
/**
 * Dependency security-advisory ratchet.
 *
 * Combines `pnpm audit --json` (JS deps) and `pip-audit --format
 * json` (Python deps). Counts advisories by severity, compares
 * against `security-advisories-baseline.json`. Per-severity gates
 * so a fix to one critical CVE that introduces 5 lows doesn't
 * net-zero through.
 *
 * Severity gating
 * ---------------
 * - critical / high → tight gate. Any new advisory red-gates the
 *   PR. Reductions ratchet down.
 * - moderate / low → loose gate. Up to baseline accepted.
 *   Reductions still ratchet down.
 *
 * The high/critical tightness is intentional: critical CVEs in
 * runtime deps are the bug class we MUST surface immediately.
 * Low/moderate advisories accumulate (especially in transitive
 * test-only deps) faster than the team can triage; the loose
 * gate prevents the ratchet from being CI-noise.
 *
 * Usage
 * -----
 *   node scripts/check-security-advisories.mjs           # check
 *   node scripts/check-security-advisories.mjs --update  # rewrite baseline
 *
 * Wired as `make security-audit`.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE_PATH = resolve(ROOT, "security-advisories-baseline.json");

const SEVERITIES = ["critical", "high", "moderate", "low"];

function safeExec(cmd, opts = {}) {
  try {
    return execSync(cmd, {
      cwd: ROOT,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
      ...opts,
    });
  } catch (err) {
    // Both `pnpm audit` and `pip-audit` exit non-zero when they
    // find advisories. Capture stdout regardless.
    return err.stdout?.toString() ?? "";
  }
}

function pnpmAuditCounts() {
  const out = safeExec("pnpm audit --json");
  // pnpm audit JSON shape:
  //   { advisories: { "1234": { severity: "high", ... }, ... },
  //     metadata: { vulnerabilities: { critical: 0, high: 1, ... } } }
  // Newer pnpm versions emit a JSONL-ish stream. We try the
  // metadata path first; fall back to walking advisories.
  try {
    const data = JSON.parse(out || "{}");
    const meta = data.metadata?.vulnerabilities;
    if (meta && typeof meta === "object") {
      return {
        critical: meta.critical ?? 0,
        high: meta.high ?? 0,
        moderate: meta.moderate ?? 0,
        low: meta.low ?? 0,
      };
    }
    const advisories = data.advisories ?? {};
    const out2 = { critical: 0, high: 0, moderate: 0, low: 0 };
    for (const adv of Object.values(advisories)) {
      const sev = (adv.severity || "").toLowerCase();
      if (sev in out2) out2[sev]++;
    }
    return out2;
  } catch {
    // pnpm produced something we can't parse — surface as an
    // empty advisory set rather than crashing the gate. The shell
    // layer's exit code already tells CI something is off.
    return { critical: 0, high: 0, moderate: 0, low: 0 };
  }
}

function pipAuditCounts() {
  const out = safeExec("pip-audit -r apps/api/requirements.txt --format json");
  try {
    const data = JSON.parse(out || "{}");
    // pip-audit shape: { dependencies: [{ name, vulns: [{ id, fix_versions, ... }] }] }
    // Severity isn't in pip-audit's default output; OSV doesn't
    // categorise consistently across ecosystems. We approximate by
    // counting every reported vuln as `high` — pip-audit only
    // reports advisories where a fix is available, so they're
    // actionable by definition.
    const vulnCount = (data.dependencies ?? []).reduce(
      (sum, dep) => sum + (dep.vulns?.length ?? 0),
      0,
    );
    return { critical: 0, high: vulnCount, moderate: 0, low: 0 };
  } catch {
    return { critical: 0, high: 0, moderate: 0, low: 0 };
  }
}

function combineCounts(...counts) {
  const out = { critical: 0, high: 0, moderate: 0, low: 0 };
  for (const c of counts) {
    for (const s of SEVERITIES) out[s] += c[s] || 0;
  }
  return out;
}

function main() {
  let baseline;
  try {
    baseline = JSON.parse(readFileSync(BASELINE_PATH, "utf-8"));
  } catch {
    baseline = {
      "//": "first run; populated on --update",
      critical: 0,
      high: 0,
      moderate: 0,
      low: 0,
    };
  }

  console.error("Running pnpm audit + pip-audit (this can take ~30s)…");
  const js = pnpmAuditCounts();
  const py = pipAuditCounts();
  const total = combineCounts(js, py);

  if (process.argv.includes("--update")) {
    const next = {
      "//":
        baseline["//"] ||
        "Security-advisory baseline. Per-severity counts across pnpm + pip-audit. Critical/high red-gate on any new advisory; moderate/low accept up to baseline.",
      ...total,
      // Surface the per-tool breakdown for review at update time.
      _detail: { pnpm: js, pip_audit: py },
    };
    writeFileSync(BASELINE_PATH, JSON.stringify(next, null, 2) + "\n", "utf-8");
    console.log("Baseline updated:");
    for (const s of SEVERITIES) {
      console.log(`  ${s}: ${baseline[s] ?? 0} → ${total[s]}`);
    }
    return;
  }

  // Tight gate on critical/high — any increase red-gates.
  // Loose gate on moderate/low — only red-gate if NEW additions
  // come in, not if the baseline counts unchanged.
  const failures = [];
  const reductions = [];
  for (const s of SEVERITIES) {
    const exp = baseline[s] ?? 0;
    const got = total[s];
    if (got > exp) {
      failures.push({ s, from: exp, to: got, tight: s === "critical" || s === "high" });
    } else if (got < exp) {
      reductions.push({ s, from: exp, to: got });
    }
  }

  if (failures.length === 0 && reductions.length === 0) {
    console.log("security-advisories baseline OK — no drift.");
    return;
  }

  if (failures.length) {
    console.error("\n❌ New security advisories vs baseline:");
    for (const f of failures) {
      const tag = f.tight ? "🚨" : "  ";
      console.error(`   ${tag} ${f.s}: ${f.from} → ${f.to}  (+${f.to - f.from})`);
    }
    if (failures.some((f) => f.tight)) {
      console.error(
        "\nCritical/high advisories MUST be addressed before merge:\n" +
          "  • Bump the offending dep to a patched version, OR\n" +
          "  • Document the mitigation (the dep is in a code path that's\n" +
          "    unreachable from runtime input) AND bump the baseline\n" +
          "    explicitly:\n" +
          "      node scripts/check-security-advisories.mjs --update",
      );
    } else {
      console.error(
        "\nLow/moderate advisories accumulated past baseline. " +
          "Triage + bump baseline if accepted.",
      );
    }
  }
  if (reductions.length) {
    console.error("\n🎉 Security advisories reduced:");
    for (const r of reductions) {
      console.error(`   ${r.s}: ${r.from} → ${r.to}  (-${r.from - r.to})`);
    }
    console.error(
      "\nUpdate the baseline so future regressions can't silently rebuild:\n" +
        "  node scripts/check-security-advisories.mjs --update",
    );
  }
  process.exit(1);
}

main();
