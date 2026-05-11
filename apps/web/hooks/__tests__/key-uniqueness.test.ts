import { describe, expect, test } from "vitest";

/**
 * TanStack query-key uniqueness contract.
 *
 * The bug class
 * -------------
 * TanStack Query identifies cached queries by their key tuple. Two
 * hooks accidentally producing the same key tuple cause cache
 * cross-pollination — invalidating one would refetch the other,
 * mutating one's cache writes the other's, and the UI surface is
 * "why did my Tasks list refresh when I edited a ChangeOrder?".
 *
 * Runtime tests can't see this. Each hook has its own test that
 * mocks fetch and asserts on the URL — none of them ever look at
 * the queryKey tuple. The only practical gate is a static walk
 * across every module's `*Keys` export.
 *
 * What we pin
 * -----------
 * 1. Every module's top-level `all` key is unique across all 14
 *    modules. Two modules sharing `["foo"]` would collide on
 *    every cross-module invalidation pattern.
 * 2. Every key-builder function returns a tuple whose first element
 *    is the module's own `all[0]`. Catches "I copy-pasted from
 *    pulse and forgot to rename `pulse` → `winwork`."
 * 3. No two key-builder functions across all modules produce the
 *    same tuple when called with synthetic inputs. The synthetic
 *    inputs are stable per-builder (same UUID for every "id"
 *    argument, same {} for every filter argument) — so two builders
 *    that DO collide will collide on these inputs reliably.
 *
 * Why representative inputs (not random)
 * --------------------------------------
 * fast-check sweep is overkill here — the bug shape is "two builders
 * structurally produce the same tuple for the same input class," not
 * "they collide on rare value combinations." A single representative
 * input per type catches every collision the user could trip in
 * production. Random inputs would just add CI flake surface.
 */

// Import names mirror each module's actual `export const` — these are
// not consistent across the codebase (`changeOrderKeys` vs
// `changeorderKeys` is a real divergence). The test treats each as
// opaque; only the value shape matters.
import { activityKeys } from "@/hooks/activity/keys";
import { bidradarKeys } from "@/hooks/bidradar/keys";
import { changeOrderKeys } from "@/hooks/changeorder/keys";
import { codeguardKeys } from "@/hooks/codeguard/keys";
import { dailylogKeys } from "@/hooks/dailylog/keys";
import { drawbridgeKeys } from "@/hooks/drawbridge/keys";
import { handoverKeys } from "@/hooks/handover/keys";
import { projectKeys } from "@/hooks/projects/keys";
import { pulseKeys } from "@/hooks/pulse/keys";
import { punchListKeys } from "@/hooks/punchlist/keys";
import { scheduleKeys } from "@/hooks/schedule/keys";
import { siteeyeKeys } from "@/hooks/siteeye/keys";
import { submittalsKeys } from "@/hooks/submittals/keys";
import { winworkKeys } from "@/hooks/winwork/keys";

// Synthetic inputs. Same value per type across every builder so two
// builders that share a structure collide reliably.
const ID = "00000000-0000-0000-0000-000000000001";
const FILTERS = {} as const;

interface KeyModule {
  name: string;
  obj: Record<string, unknown>;
}

const MODULES: KeyModule[] = [
  { name: "activity", obj: activityKeys },
  { name: "bidradar", obj: bidradarKeys },
  { name: "changeorder", obj: changeOrderKeys },
  { name: "codeguard", obj: codeguardKeys },
  { name: "dailylog", obj: dailylogKeys },
  { name: "drawbridge", obj: drawbridgeKeys },
  { name: "handover", obj: handoverKeys },
  { name: "projects", obj: projectKeys },
  { name: "pulse", obj: pulseKeys },
  { name: "punchlist", obj: punchListKeys },
  { name: "schedule", obj: scheduleKeys },
  { name: "siteeye", obj: siteeyeKeys },
  { name: "submittals", obj: submittalsKeys },
  { name: "winwork", obj: winworkKeys },
];

/**
 * Call a key-builder with a representative input shape.
 *
 * We don't know each builder's parameter signature statically, so
 * we try a small set of common shapes (no-arg, one ID, one filter
 * object, two args) and use the first that doesn't throw. The first
 * non-throwing call gives us a representative tuple to compare.
 */
function callBuilder(fn: (...args: unknown[]) => readonly unknown[]): readonly unknown[] | null {
  const attempts: unknown[][] = [
    [],
    [ID],
    [FILTERS],
    [ID, ID],
    [ID, FILTERS],
    [ID, undefined],
  ];
  for (const args of attempts) {
    try {
      const result = fn(...args);
      if (Array.isArray(result)) return result as readonly unknown[];
    } catch {
      // try the next signature
    }
  }
  return null;
}

interface Pinned {
  module: string;
  builder: string;
  key: readonly unknown[];
  serialized: string;
}

function collectAllKeys(): Pinned[] {
  const out: Pinned[] = [];
  for (const { name, obj } of MODULES) {
    for (const [builderName, value] of Object.entries(obj)) {
      let key: readonly unknown[] | null = null;
      if (Array.isArray(value)) {
        // Static `all` array.
        key = value;
      } else if (typeof value === "function") {
        key = callBuilder(value as (...a: unknown[]) => readonly unknown[]);
      }
      if (!key) continue;
      out.push({
        module: name,
        builder: builderName,
        key,
        serialized: JSON.stringify(key),
      });
    }
  }
  return out;
}

describe("query-key uniqueness", () => {
  test("every module's top-level `all` is a unique singleton", () => {
    // The cross-module isolation hinges on `all[0]` being unique. A
    // duplicate would mean every `invalidateQueries({ queryKey: X.all })`
    // also blasts the colliding module's cache.
    const seen = new Map<string, string>(); // serialized → module name
    const collisions: string[] = [];
    for (const { name, obj } of MODULES) {
      const all = obj.all;
      if (!Array.isArray(all)) continue;
      const ser = JSON.stringify(all);
      const prior = seen.get(ser);
      if (prior) {
        collisions.push(`${name}.all === ${prior}.all (${ser})`);
      }
      seen.set(ser, name);
    }
    expect(collisions).toEqual([]);
  });

  test("every key-builder's first element matches the module's `all[0]` prefix", () => {
    // Catches "copy-pasted pulse keys into winwork and forgot to
    // rename the literal." Such a regression would route every
    // winwork query through pulse's cache namespace — invalidations
    // would cross modules and the UI would behave inconsistently.
    const violations: string[] = [];
    for (const { name, obj } of MODULES) {
      const all = obj.all as readonly unknown[];
      const expectedPrefix = all[0];
      for (const [builderName, value] of Object.entries(obj)) {
        if (builderName === "all") continue;
        let key: readonly unknown[] | null = null;
        if (Array.isArray(value)) key = value;
        else if (typeof value === "function") {
          key = callBuilder(value as (...a: unknown[]) => readonly unknown[]);
        }
        if (!key || key.length === 0) continue;
        if (key[0] !== expectedPrefix) {
          violations.push(
            `${name}.${builderName} → key[0]=${JSON.stringify(key[0])}, ` +
              `expected ${JSON.stringify(expectedPrefix)} ` +
              "(must match this module's `all[0]`)",
          );
        }
      }
    }
    expect(violations, violations.join("\n")).toEqual([]);
  });

  test("no two key-builders produce the same tuple for representative inputs", () => {
    // The strongest cross-module invariant: even with all the
    // structural rules satisfied, two builders could still happen to
    // produce the same exact tuple (e.g. via shared filter shapes).
    // Generate one tuple per builder + assert every serialised tuple
    // is unique.
    const all = collectAllKeys();
    const byKey = new Map<string, string[]>();
    for (const p of all) {
      const id = `${p.module}.${p.builder}`;
      if (!byKey.has(p.serialized)) byKey.set(p.serialized, []);
      byKey.get(p.serialized)!.push(id);
    }

    const collisions: string[] = [];
    for (const [serialized, builders] of byKey) {
      if (builders.length > 1) {
        collisions.push(`${builders.join(" ↔ ")}\n    key=${serialized}`);
      }
    }
    expect(collisions, collisions.join("\n\n")).toEqual([]);
  });

  test("every module exposes at least an `all` plus one builder", () => {
    // Defensive sanity: a module that exports an empty `*Keys` object
    // would silently pass every test above. Pin a minimum so a future
    // refactor that broke the export shape surfaces here.
    for (const { name, obj } of MODULES) {
      expect(Array.isArray(obj.all), `${name}.all must be a tuple`).toBe(true);
      const builderCount = Object.entries(obj).filter(
        ([k, v]) => k !== "all" && (typeof v === "function" || Array.isArray(v)),
      ).length;
      expect(builderCount, `${name} should have ≥1 key builder beyond .all`).toBeGreaterThanOrEqual(1);
    }
  });
});
