/**
 * VND currency formatter (cycle AA1, TS half).
 *
 * Pinned seams:
 *   1. VND_SYMBOL is U+20AB (đồng sign), not 'đ' or 'VND'.
 *   2. VND_THOUSANDS_SEPARATOR is '.' (Vietnamese convention).
 *   3. formatVND(12345678) === '12.345.678 ₫'.
 *   4. parseVND round-trips formatVND output.
 *   5. null / undefined / NaN / Infinity → '' (no-op for chained renderers).
 *   6. parseVND graceful null on non-numeric input.
 */

import { describe, expect, it } from "vitest";

import {
  VND_SYMBOL,
  VND_THOUSANDS_SEPARATOR,
  formatVND,
  parseVND,
} from "../format-vnd";


// ---------- Constants ----------


describe("VND_SYMBOL", () => {
  it("is the Vietnamese đồng sign U+20AB", () => {
    expect(VND_SYMBOL).toBe("₫");
    // Pin: NOT 'đ' (lowercase d-stroke) and NOT 'VND' (text abbrev).
    expect(VND_SYMBOL).not.toBe("đ");
    expect(VND_SYMBOL).not.toBe("VND");
  });
});


describe("VND_THOUSANDS_SEPARATOR", () => {
  it("is a dot — Vietnamese convention", () => {
    expect(VND_THOUSANDS_SEPARATOR).toBe(".");
  });
});


// ---------- formatVND ----------


describe("formatVND", () => {
  it("formats whole VND with dot thousands and ₫ suffix", () => {
    expect(formatVND(12345678)).toBe("12.345.678 ₫");
  });

  it("formats small amounts without separators", () => {
    expect(formatVND(0)).toBe("0 ₫");
    expect(formatVND(99)).toBe("99 ₫");
    expect(formatVND(999)).toBe("999 ₫");
    expect(formatVND(1000)).toBe("1.000 ₫");
  });

  it("formats large amounts with multiple separators", () => {
    expect(formatVND(1_000_000_000)).toBe("1.000.000.000 ₫");
  });

  it("rounds fractional amounts to integer (VND has no decimal)", () => {
    expect(formatVND(1234.4)).toBe("1.234 ₫");
    expect(formatVND(1234.5)).toBe("1.235 ₫");
  });

  it("renders negatives with leading sign", () => {
    expect(formatVND(-12345)).toBe("-12.345 ₫");
  });

  it("returns '' for null / undefined / NaN / Infinity", () => {
    expect(formatVND(null)).toBe("");
    expect(formatVND(undefined)).toBe("");
    expect(formatVND(Number.NaN)).toBe("");
    expect(formatVND(Number.POSITIVE_INFINITY)).toBe("");
    expect(formatVND(Number.NEGATIVE_INFINITY)).toBe("");
  });
});


// ---------- parseVND ----------


describe("parseVND", () => {
  it("round-trips formatVND output", () => {
    expect(parseVND("12.345.678 ₫")).toBe(12345678);
  });

  it("accepts plain integer strings", () => {
    expect(parseVND("12345678")).toBe(12345678);
    expect(parseVND("0")).toBe(0);
  });

  it("accepts amounts without the symbol", () => {
    expect(parseVND("12.345.678")).toBe(12345678);
  });

  it("accepts the lowercase 'đ' alternative", () => {
    // Hand-typed 'đ' is the most common informal symbol — accept
    // so a saved URL like `?max_amount=12.345.678 đ` works.
    expect(parseVND("12.345.678 đ")).toBe(12345678);
  });

  it("accepts the 'VND' text suffix (case-insensitive)", () => {
    expect(parseVND("12345678 VND")).toBe(12345678);
    expect(parseVND("12345678 vnd")).toBe(12345678);
  });

  it("handles negative amounts", () => {
    expect(parseVND("-12.345 ₫")).toBe(-12345);
  });

  it("returns null for empty / null / undefined", () => {
    expect(parseVND(null)).toBeNull();
    expect(parseVND(undefined)).toBeNull();
    expect(parseVND("")).toBeNull();
  });

  it("returns null for non-numeric input", () => {
    // Stale URLs with `?max_amount=một triệu` shouldn't crash —
    // graceful null fallback.
    expect(parseVND("abc")).toBeNull();
    expect(parseVND("một triệu")).toBeNull();
  });

  it("returns null for input that strips to empty", () => {
    // After stripping symbol + đ|VND + dots, this becomes "".
    expect(parseVND("...")).toBeNull();
    expect(parseVND("₫")).toBeNull();
  });
});
