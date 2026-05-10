/**
 * File hash prefix display (cycle PP1).
 *
 * Pinned seams:
 *   1. ELLIPSIS = "…" (U+2026, single char).
 *   2. Default length 7 (git-style).
 *   3. Length out of [4, 64] → "".
 *   4. Lowercased output.
 *   5. Whitespace + outer quotes stripped.
 *   6. Non-hex → "".
 *   7. Length >= digest length → no ellipsis.
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_HASH_PREFIX_LENGTH,
  ELLIPSIS,
  MAX_HASH_PREFIX_LENGTH,
  MIN_HASH_PREFIX_LENGTH,
  formatHashPrefix,
} from "../format-hash-prefix";


// ---------- Constants ----------


describe("constants", () => {
  it("MIN_HASH_PREFIX_LENGTH = 4", () => {
    expect(MIN_HASH_PREFIX_LENGTH).toBe(4);
  });

  it("MAX_HASH_PREFIX_LENGTH = 64 (full SHA-256)", () => {
    expect(MAX_HASH_PREFIX_LENGTH).toBe(64);
  });

  it("DEFAULT_HASH_PREFIX_LENGTH = 7 (git-style)", () => {
    expect(DEFAULT_HASH_PREFIX_LENGTH).toBe(7);
  });

  it("ELLIPSIS is U+2026 single char (NOT three dots)", () => {
    expect(ELLIPSIS).toBe("…");
    expect(ELLIPSIS.length).toBe(1);
    expect(ELLIPSIS).not.toBe("...");
  });
});


// ---------- Truncation ----------


describe("formatHashPrefix — truncation", () => {
  it("truncates to default length 7 + ellipsis", () => {
    expect(formatHashPrefix("a1b2c3d4e5f6")).toBe("a1b2c3d…");
  });

  it("custom length", () => {
    expect(formatHashPrefix("a1b2c3d4e5f6", 4)).toBe("a1b2…");
  });

  it("length at max", () => {
    const sha = "a".repeat(64);
    expect(formatHashPrefix(sha, 64)).toBe(sha);
  });

  it("returns full digest with no ellipsis when length >= digest", () => {
    expect(formatHashPrefix("a1b2c3", 7)).toBe("a1b2c3");
    expect(formatHashPrefix("a1b2c3", 6)).toBe("a1b2c3");
  });
});


// ---------- Case folding ----------


describe("formatHashPrefix — normalization", () => {
  it("lowercases output", () => {
    expect(formatHashPrefix("A1B2C3D4E5F6")).toBe("a1b2c3d…");
  });

  it("mixed case lowercases", () => {
    expect(formatHashPrefix("AbCdEf01234")).toBe("abcdef0…");
  });
});


// ---------- Whitespace + quotes ----------


describe("formatHashPrefix — input cleanup", () => {
  it("strips boundary whitespace", () => {
    expect(formatHashPrefix("  a1b2c3d4e5f6  ")).toBe("a1b2c3d…");
  });

  it("strips outer double quotes", () => {
    expect(formatHashPrefix('"a1b2c3d4e5f6"')).toBe("a1b2c3d…");
  });

  it("strips outer single quotes", () => {
    expect(formatHashPrefix("'a1b2c3d4e5f6'")).toBe("a1b2c3d…");
  });

  it("does not strip mismatched quotes", () => {
    // `"abc'` is NOT a valid quoted string — leave as-is, then
    // hex check fails → "".
    expect(formatHashPrefix("\"a1b2c3'")).toBe("");
  });
});


// ---------- Length validation ----------


describe("formatHashPrefix — length bounds", () => {
  it("returns '' for length below MIN", () => {
    // Cardinal pin: out-of-range length → "" (NOT clamped).
    // Surfaces config bug rather than silently truncating.
    expect(formatHashPrefix("a1b2c3d4", 3)).toBe("");
    expect(formatHashPrefix("a1b2c3d4", 0)).toBe("");
  });

  it("returns '' for length above MAX", () => {
    expect(formatHashPrefix("a1b2c3d4", 65)).toBe("");
    expect(formatHashPrefix("a1b2c3d4", 100)).toBe("");
  });

  it("accepts length at MIN boundary", () => {
    expect(formatHashPrefix("a1b2c3d4", 4)).toBe("a1b2…");
  });

  it("accepts length at MAX boundary", () => {
    const sha = "a".repeat(64);
    expect(formatHashPrefix(sha, 64)).toBe(sha);
  });
});


// ---------- Non-hex rejection ----------


describe("formatHashPrefix — non-hex", () => {
  it("rejects non-hex characters", () => {
    expect(formatHashPrefix("not-a-hash")).toBe("");
    expect(formatHashPrefix("ghijkl")).toBe("");  // g+ not hex
    expect(formatHashPrefix("a1b2c3z")).toBe("");
  });

  it("rejects spaces in middle", () => {
    expect(formatHashPrefix("a1 b2c3")).toBe("");
  });
});


// ---------- Defensive ----------


describe("formatHashPrefix — defensive", () => {
  it("returns '' for null / undefined / empty", () => {
    expect(formatHashPrefix(null)).toBe("");
    expect(formatHashPrefix(undefined)).toBe("");
    expect(formatHashPrefix("")).toBe("");
  });

  it("returns '' for whitespace-only", () => {
    expect(formatHashPrefix("   ")).toBe("");
  });
});
