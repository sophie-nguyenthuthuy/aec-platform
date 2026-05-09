import { describe, expect, test } from "vitest";

import en from "../messages/en.json";
import vi from "../messages/vi.json";

/**
 * vi/en key parity.
 *
 * `next-intl` (the i18n layer the app uses) does NOT throw on a
 * missing key — it silently falls back to the key path itself
 * ("winwork.status.draft") rendered as visible text. Worse, when only
 * ONE locale is missing a key, that locale's users see an English
 * fallback OR the raw path — both equally broken, both invisible at
 * code-review time.
 *
 * This test asserts the two key sets are identical. New strings must
 * land in BOTH files in the same PR — there is no "I'll add the
 * Vietnamese later" branch in our tree, because "later" never comes.
 *
 * The test does NOT assert on values — translations legitimately
 * differ in length / formatting / pluralisation, and forcing them to
 * match would just make the assertion useless. Key-set parity is the
 * narrow but high-leverage invariant.
 */

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/**
 * Recursively flatten a nested JSON object into dotted-path keys.
 * Leaves are anything non-plain-object (strings, arrays, numbers).
 *
 * Why we treat arrays as leaves: a few of our message files use
 * arrays for ICU select-options. A regression that added a new
 * option in en.json but not vi.json wouldn't show up at the per-
 * element level — but the key for the parent IS shared, and the
 * value-shape divergence is what the test exists to surface. We
 * surface it via a length comparison instead.
 */
function flatten(obj: JsonValue, prefix = ""): Map<string, JsonValue> {
  const out = new Map<string, JsonValue>();
  if (
    obj === null ||
    typeof obj !== "object" ||
    Array.isArray(obj)
  ) {
    out.set(prefix, obj);
    return out;
  }
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    for (const [innerK, innerV] of flatten(v as JsonValue, path)) {
      out.set(innerK, innerV);
    }
  }
  return out;
}

describe("i18n / key parity", () => {
  const enFlat = flatten(en as JsonValue);
  const viFlat = flatten(vi as JsonValue);

  test("every English key has a Vietnamese counterpart", () => {
    const missing = [...enFlat.keys()].filter((k) => !viFlat.has(k));
    expect(missing, `vi.json missing ${missing.length} keys: ${missing.slice(0, 10).join(", ")}`).toEqual([]);
  });

  test("every Vietnamese key has an English counterpart", () => {
    // The reverse direction catches "translator added a vi key that
    // doesn't exist in en" — usually a leftover from a moved/renamed
    // string the en side already deleted.
    const missing = [...viFlat.keys()].filter((k) => !enFlat.has(k));
    expect(missing, `en.json missing ${missing.length} keys: ${missing.slice(0, 10).join(", ")}`).toEqual([]);
  });

  test("array-valued keys have the same length in both locales", () => {
    // ICU select / pluralisation arrays must agree in arity. A
    // length mismatch usually means one locale forgot a new option.
    const drift: string[] = [];
    for (const [key, enVal] of enFlat) {
      if (!Array.isArray(enVal)) continue;
      const viVal = viFlat.get(key);
      if (!Array.isArray(viVal) || viVal.length !== enVal.length) {
        drift.push(`${key}: en=${enVal.length} vs vi=${Array.isArray(viVal) ? viVal.length : "<missing>"}`);
      }
    }
    expect(drift).toEqual([]);
  });

  test("no key has an empty-string value in either locale", () => {
    // Empty strings render as nothing — usually a translation that
    // was started and never finished. Easy to miss in review.
    const empty: string[] = [];
    for (const [k, v] of enFlat) if (v === "") empty.push(`en:${k}`);
    for (const [k, v] of viFlat) if (v === "") empty.push(`vi:${k}`);
    expect(empty).toEqual([]);
  });

  test("ICU placeholders ({name}, {count}) appear in BOTH locales for the same key", () => {
    // If en says "Welcome, {name}" and vi forgot the {name}, the
    // user sees "Chào mừng" and the variable disappears. Pin
    // placeholder parity at the regex level — values still diverge
    // freely; only the {…} tokens must match as a multiset.
    const re = /\{[a-zA-Z_][a-zA-Z0-9_]*\}/g;
    const drift: string[] = [];
    for (const [key, enVal] of enFlat) {
      if (typeof enVal !== "string") continue;
      const viVal = viFlat.get(key);
      if (typeof viVal !== "string") continue;
      const enTokens = (enVal.match(re) ?? []).slice().sort();
      const viTokens = (viVal.match(re) ?? []).slice().sort();
      if (JSON.stringify(enTokens) !== JSON.stringify(viTokens)) {
        drift.push(`${key}: en=[${enTokens.join(",")}] vs vi=[${viTokens.join(",")}]`);
      }
    }
    expect(drift, drift.slice(0, 5).join("\n")).toEqual([]);
  });
});
