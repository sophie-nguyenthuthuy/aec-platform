/**
 * Slug canonicalizer (cycle CC3, TS half).
 *
 * Pinned seams:
 *   1. MAX_SLUG_LENGTH = 64 (matches API varchar(64)).
 *   2. VN diacritics stripped (delegates to BB3, including đ → d).
 *   3. Lowercase.
 *   4. Non-alphanumeric runs collapsed to single hyphen.
 *   5. Leading/trailing hyphens trimmed.
 *   6. Capped at MAX_SLUG_LENGTH; trailing hyphen re-trimmed.
 *   7. Idempotent: canonicalSlug(canonicalSlug(x)) === canonicalSlug(x).
 *   8. null / undefined / empty / all-non-alphanum → "".
 */

import { describe, expect, it } from "vitest";

import { MAX_SLUG_LENGTH, canonicalSlug } from "../canonical-slug";


describe("MAX_SLUG_LENGTH", () => {
  it("is 64 — matches API slug column varchar(64)", () => {
    // Pin so a refactor that bumps the column without updating
    // this constant surfaces in tests (mismatched length would
    // cause an API 422 on edge-case long inputs).
    expect(MAX_SLUG_LENGTH).toBe(64);
  });
});


describe("canonicalSlug — VN inputs", () => {
  it("strips diacritics from a VN org name", () => {
    expect(canonicalSlug("Hà Nội Construction Co.")).toBe("ha-noi-construction-co");
  });

  it("folds đ → d via BB3 strip", () => {
    expect(canonicalSlug("Đại Phát Group")).toBe("dai-phat-group");
  });

  it("uppercase Đ folds to lowercase d", () => {
    expect(canonicalSlug("ĐÔNG ANH")).toBe("dong-anh");
  });
});


describe("canonicalSlug — formatting rules", () => {
  it("lowercases", () => {
    expect(canonicalSlug("Foo Bar")).toBe("foo-bar");
    expect(canonicalSlug("FOOBAR")).toBe("foobar");
  });

  it("collapses multiple spaces to single hyphen", () => {
    expect(canonicalSlug("foo  bar")).toBe("foo-bar");
    expect(canonicalSlug("foo   bar")).toBe("foo-bar");
  });

  it("collapses non-alphanumeric runs to single hyphen", () => {
    expect(canonicalSlug("foo!@#bar")).toBe("foo-bar");
    expect(canonicalSlug("foo--bar")).toBe("foo-bar");
    expect(canonicalSlug("foo___bar")).toBe("foo-bar");
  });

  it("trims leading and trailing hyphens", () => {
    expect(canonicalSlug("  foo bar  ")).toBe("foo-bar");
    expect(canonicalSlug("---foo---")).toBe("foo");
    expect(canonicalSlug("...foo...")).toBe("foo");
  });

  it("preserves alphanumeric characters", () => {
    expect(canonicalSlug("abc123")).toBe("abc123");
    expect(canonicalSlug("project-2026")).toBe("project-2026");
  });

  it("handles apostrophes (collapse to hyphen)", () => {
    // "Foo's Bar" → strip → "Foo's Bar" → lowercase → "foo's bar"
    // → collapse [^a-z0-9]+ → "foo-s-bar". Pin: the apostrophe
    // becomes a separator, not silently dropped.
    expect(canonicalSlug("Foo's Bar")).toBe("foo-s-bar");
  });
});


describe("canonicalSlug — defensive", () => {
  it("returns '' for null / undefined / empty", () => {
    expect(canonicalSlug(null)).toBe("");
    expect(canonicalSlug(undefined)).toBe("");
    expect(canonicalSlug("")).toBe("");
  });

  it("returns '' when input strips to no alphanumerics", () => {
    expect(canonicalSlug("!!!")).toBe("");
    expect(canonicalSlug("---")).toBe("");
    expect(canonicalSlug("   ")).toBe("");
    // VN diacritics over no base letters? `̀` (combining grave)
    // alone strips to empty.
    expect(canonicalSlug("...")).toBe("");
  });
});


describe("canonicalSlug — length cap", () => {
  it("caps at MAX_SLUG_LENGTH", () => {
    const long = "a".repeat(100);
    const out = canonicalSlug(long);
    expect(out.length).toBe(MAX_SLUG_LENGTH);
    expect(out).toBe("a".repeat(MAX_SLUG_LENGTH));
  });

  it("trims trailing hyphen when cap lands on one", () => {
    // 32-char "abc-" repeated, capped at 64 — would land mid-hyphen.
    // Construct: "ab-".repeat(30) = 90 chars; cap 64 lands inside
    // a hyphen-anchor depending on alignment.
    const tricky = "ab-".repeat(30); // 90 chars: "ab-ab-ab-...-ab-"
    const out = canonicalSlug(tricky);
    expect(out.length).toBeLessThanOrEqual(MAX_SLUG_LENGTH);
    // Pin: trailing hyphen must NOT be present after the cap.
    expect(out.endsWith("-")).toBe(false);
  });

  it("does not cap when input is short", () => {
    const short = "abc-def";
    expect(canonicalSlug(short)).toBe("abc-def");
    expect(canonicalSlug(short).length).toBe(7);
  });
});


describe("canonicalSlug — idempotency", () => {
  it("applying twice yields the same result", () => {
    const cases = [
      "Hà Nội Construction Co.",
      "Foo  Bar",
      "ĐÔNG ANH",
      "foo-bar",
      "abc-123",
    ];
    for (const input of cases) {
      const once = canonicalSlug(input);
      const twice = canonicalSlug(once);
      expect(twice).toBe(once);
    }
  });
});
