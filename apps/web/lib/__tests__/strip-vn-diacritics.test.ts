/**
 * Vietnamese diacritic stripping for search (cycle BB3, TS half).
 *
 * Pinned seams:
 *   1. đ → d, Đ → D (NFD doesn't decompose these — explicit fold).
 *   2. All 6 tone marks on 'a' fold to 'a'.
 *   3. All 5 vowel modifications fold to base vowel.
 *   4. Uppercase versions fold to uppercase ASCII.
 *   5. ASCII passes through unchanged.
 *   6. null / undefined / empty → "".
 *   7. Idempotent on repeat application.
 */

import { describe, expect, it } from "vitest";

import { stripVNDiacritics } from "../strip-vn-diacritics";


describe("stripVNDiacritics", () => {
  it("strips diacritics from common VN place names", () => {
    expect(stripVNDiacritics("Hà Nội")).toBe("Ha Noi");
    expect(stripVNDiacritics("Đà Nẵng")).toBe("Da Nang");
    expect(stripVNDiacritics("Sài Gòn")).toBe("Sai Gon");
    expect(stripVNDiacritics("Huế")).toBe("Hue");
  });

  it("handles full personal names", () => {
    expect(stripVNDiacritics("Trần Hưng Đạo")).toBe("Tran Hung Dao");
    expect(stripVNDiacritics("Nguyễn Văn Anh")).toBe("Nguyen Van Anh");
  });

  it("folds đ → d (NFD doesn't decompose this — explicit fold)", () => {
    // Pin: NFD-only normalisation would leave đ untouched. The
    // explicit fold is the critical Vietnamese-specific case.
    expect(stripVNDiacritics("đường")).toBe("duong");
    expect(stripVNDiacritics("đẹp")).toBe("dep");
  });

  it("folds Đ → D (uppercase)", () => {
    expect(stripVNDiacritics("Đại học")).toBe("Dai hoc");
    expect(stripVNDiacritics("ĐÔNG")).toBe("DONG");
  });

  it("folds all 6 tone marks on 'a'", () => {
    // a (none), á (acute), à (grave), ả (hook), ã (tilde), ạ (dot below).
    expect(stripVNDiacritics("a á à ả ã ạ")).toBe("a a a a a a");
  });

  it("folds vowel modifications: ă, â, ê, ô, ơ, ư", () => {
    // The 6 modified-vowel base forms (each can also carry tones).
    expect(stripVNDiacritics("ă â ê ô ơ ư")).toBe("a a e o o u");
  });

  it("folds all tones on 'o' (5-vowel × 6-tone × 3-modifier table)", () => {
    // ó ò ỏ õ ọ ô ố ồ ổ ỗ ộ ơ ớ ờ ở ỡ ợ — every modified-tone
    // combination folds to 'o'.
    const allO = "ó ò ỏ õ ọ ô ố ồ ổ ỗ ộ ơ ớ ờ ở ỡ ợ";
    expect(stripVNDiacritics(allO)).toBe("o o o o o o o o o o o o o o o o o");
  });

  it("preserves ASCII characters unchanged", () => {
    expect(stripVNDiacritics("Plain ASCII")).toBe("Plain ASCII");
    expect(stripVNDiacritics("hello world 123")).toBe("hello world 123");
    expect(stripVNDiacritics("a-b_c.d")).toBe("a-b_c.d");
  });

  it("preserves whitespace and punctuation", () => {
    expect(stripVNDiacritics("Hà   Nội!")).toBe("Ha   Noi!");
    expect(stripVNDiacritics("Một, hai, ba.")).toBe("Mot, hai, ba.");
  });

  it("returns '' for null / undefined / empty", () => {
    // Calling code can chain `stripVNDiacritics(query)` without
    // a null check before lowercasing.
    expect(stripVNDiacritics(null)).toBe("");
    expect(stripVNDiacritics(undefined)).toBe("");
    expect(stripVNDiacritics("")).toBe("");
  });

  it("is idempotent (running twice yields the same result)", () => {
    // Pin: a refactor that double-decomposes would surface here
    // (e.g. if combining marks somehow re-applied).
    const once = stripVNDiacritics("Trần Hưng Đạo");
    const twice = stripVNDiacritics(once);
    expect(twice).toBe(once);
    expect(twice).toBe("Tran Hung Dao");
  });

  it("supports the search use case: query matches title", () => {
    // The audit search canonicalises both sides; pin that the
    // canonical form of "Hà Nội" matches "Ha Noi" exactly.
    const title = stripVNDiacritics("Hà Nội");
    const query = stripVNDiacritics("Ha Noi");
    expect(title.toLowerCase()).toBe(query.toLowerCase());
  });
});
