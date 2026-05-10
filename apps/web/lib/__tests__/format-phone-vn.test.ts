/**
 * Vietnamese phone number formatter (cycle BB2, TS half).
 *
 * Pinned seams:
 *   1. VN_MOBILE_PREFIXES = {3, 5, 7, 8, 9} per MIC 2018 reorg.
 *   2. Three formats: national (default), international, e164.
 *   3. Canonical E.164 is `+84XXXXXXXXX` (no separators).
 *   4. parsePhoneVN accepts five input forms (national, e164,
 *      no-+, with-grouping ×2).
 *   5. parsePhoneVN rejects non-mobile prefixes (e.g. '1', '2').
 *   6. Invalid input → '' from formatPhoneVN, null from parsePhoneVN.
 */

import { describe, expect, it } from "vitest";

import {
  VN_MOBILE_PREFIXES,
  formatPhoneVN,
  isValidVNMobile,
  parsePhoneVN,
} from "../format-phone-vn";


// ---------- Constants ----------


describe("VN_MOBILE_PREFIXES", () => {
  it("matches MIC 2018 reorg allowlist {3, 5, 7, 8, 9}", () => {
    expect(VN_MOBILE_PREFIXES).toEqual(new Set(["3", "5", "7", "8", "9"]));
  });

  it("explicitly excludes 1, 2, 4, 6", () => {
    // Pin: a refactor that adds '1' (which used to be a valid
    // VN mobile prefix pre-2018) would break the allowlist.
    expect(VN_MOBILE_PREFIXES.has("1")).toBe(false);
    expect(VN_MOBILE_PREFIXES.has("2")).toBe(false);
    expect(VN_MOBILE_PREFIXES.has("4")).toBe(false);
    expect(VN_MOBILE_PREFIXES.has("6")).toBe(false);
  });
});


// ---------- parsePhoneVN ----------


describe("parsePhoneVN", () => {
  it("parses national form to E.164", () => {
    expect(parsePhoneVN("0901234567")).toBe("+84901234567");
  });

  it("round-trips E.164 input", () => {
    expect(parsePhoneVN("+84901234567")).toBe("+84901234567");
  });

  it("accepts country-coded form without leading +", () => {
    expect(parsePhoneVN("84901234567")).toBe("+84901234567");
  });

  it("strips spaces, hyphens, dots, parentheses", () => {
    expect(parsePhoneVN("+84 90 123 4567")).toBe("+84901234567");
    expect(parsePhoneVN("0901 234 567")).toBe("+84901234567");
    expect(parsePhoneVN("0901-234-567")).toBe("+84901234567");
    expect(parsePhoneVN("0901.234.567")).toBe("+84901234567");
    expect(parsePhoneVN("(090) 1234567")).toBe("+84901234567");
  });

  it("accepts all valid mobile prefixes", () => {
    expect(parsePhoneVN("0301234567")).toBe("+84301234567");
    expect(parsePhoneVN("0501234567")).toBe("+84501234567");
    expect(parsePhoneVN("0701234567")).toBe("+84701234567");
    expect(parsePhoneVN("0801234567")).toBe("+84801234567");
    expect(parsePhoneVN("0901234567")).toBe("+84901234567");
  });

  it("rejects non-mobile prefixes (1, 2, 4, 6)", () => {
    // '1' — pre-2018 prefix, no longer valid.
    expect(parsePhoneVN("0101234567")).toBeNull();
    // '2' — landline area code, not mobile.
    expect(parsePhoneVN("0201234567")).toBeNull();
    expect(parsePhoneVN("0401234567")).toBeNull();
    expect(parsePhoneVN("0601234567")).toBeNull();
  });

  it("rejects too-short numbers", () => {
    expect(parsePhoneVN("090123456")).toBeNull(); // 9 chars, missing 1 digit
    expect(parsePhoneVN("090")).toBeNull();
  });

  it("rejects too-long numbers", () => {
    expect(parsePhoneVN("09012345678")).toBeNull(); // 11 chars
    expect(parsePhoneVN("+849012345678")).toBeNull();
  });

  it("rejects non-digit garbage", () => {
    expect(parsePhoneVN("abc")).toBeNull();
    expect(parsePhoneVN("090abc4567")).toBeNull();
  });

  it("returns null for null / undefined / empty", () => {
    expect(parsePhoneVN(null)).toBeNull();
    expect(parsePhoneVN(undefined)).toBeNull();
    expect(parsePhoneVN("")).toBeNull();
    expect(parsePhoneVN("   ")).toBeNull(); // whitespace-only strips to ""
  });
});


// ---------- isValidVNMobile ----------


describe("isValidVNMobile", () => {
  it("returns true for valid mobile inputs", () => {
    expect(isValidVNMobile("0901234567")).toBe(true);
    expect(isValidVNMobile("+84901234567")).toBe(true);
  });

  it("returns false for invalid inputs", () => {
    expect(isValidVNMobile("0101234567")).toBe(false);
    expect(isValidVNMobile(null)).toBe(false);
    expect(isValidVNMobile("abc")).toBe(false);
  });
});


// ---------- formatPhoneVN ----------


describe("formatPhoneVN", () => {
  it("defaults to 'national' format (most common in VN UIs)", () => {
    expect(formatPhoneVN("+84901234567")).toBe("0901 234 567");
  });

  it("formats 'national' as 4-3-3 with leading 0", () => {
    expect(formatPhoneVN("+84901234567", "national")).toBe("0901 234 567");
    expect(formatPhoneVN("0901234567", "national")).toBe("0901 234 567");
  });

  it("formats 'international' as 2-3-4 after +84", () => {
    expect(formatPhoneVN("+84901234567", "international")).toBe("+84 90 123 4567");
    expect(formatPhoneVN("0901234567", "international")).toBe("+84 90 123 4567");
  });

  it("formats 'e164' with no separators", () => {
    expect(formatPhoneVN("+84901234567", "e164")).toBe("+84901234567");
    expect(formatPhoneVN("0901 234 567", "e164")).toBe("+84901234567");
  });

  it("returns '' for invalid input", () => {
    // Chained-render-friendly: `formatPhoneVN(member.phone)` works
    // without a null check.
    expect(formatPhoneVN(null)).toBe("");
    expect(formatPhoneVN(undefined)).toBe("");
    expect(formatPhoneVN("")).toBe("");
    expect(formatPhoneVN("0101234567")).toBe(""); // invalid prefix
    expect(formatPhoneVN("abc")).toBe("");
  });

  it("normalises grouping on round-trip", () => {
    // User types weird grouping; we render canonical grouping.
    expect(formatPhoneVN("0 9 0 1 2 3 4 5 6 7", "national")).toBe("0901 234 567");
  });
});
