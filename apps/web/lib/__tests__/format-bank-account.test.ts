/**
 * VN bank account number formatter (cycle HH2, TS half).
 *
 * Pinned seams:
 *   1. VN_BANKS has 12 entries (closed registry).
 *   2. MIN/MAX = 8/19 digits.
 *   3. Right-aligned 4-digit grouping (LAST group always 4).
 *   4. Leading zeros preserved.
 *   5. Whitespace + hyphens stripped on parse.
 *   6. Non-digit chars → null.
 *   7. bankDisplayName case-insensitive.
 *   8. null / empty / out-of-range → null/empty.
 */

import { describe, expect, it } from "vitest";

import {
  MAX_BANK_ACCOUNT_LENGTH,
  MIN_BANK_ACCOUNT_LENGTH,
  VN_BANKS,
  bankDisplayName,
  formatBankAccount,
  parseBankAccount,
} from "../format-bank-account";


// ---------- VN_BANKS ----------


describe("VN_BANKS", () => {
  it("has 12 entries (closed registry)", () => {
    expect(Object.keys(VN_BANKS).length).toBe(12);
  });

  it("includes the major VN banks", () => {
    expect(VN_BANKS.VCB).toBe("Vietcombank");
    expect(VN_BANKS.TCB).toBe("Techcombank");
    expect(VN_BANKS.BIDV).toBe("BIDV");
    expect(VN_BANKS.ACB).toBe("ACB");
  });

  it("uses uppercase bank codes as keys", () => {
    for (const code of Object.keys(VN_BANKS)) {
      expect(code).toBe(code.toUpperCase());
    }
  });
});


// ---------- Constants ----------


describe("limits", () => {
  it("MIN_BANK_ACCOUNT_LENGTH is 8 (legacy accounts)", () => {
    expect(MIN_BANK_ACCOUNT_LENGTH).toBe(8);
  });

  it("MAX_BANK_ACCOUNT_LENGTH is 19", () => {
    expect(MAX_BANK_ACCOUNT_LENGTH).toBe(19);
  });
});


// ---------- parseBankAccount ----------


describe("parseBankAccount", () => {
  it("accepts canonical digit string at min length", () => {
    expect(parseBankAccount("12345678")).toBe("12345678");
  });

  it("accepts canonical at max length", () => {
    const max = "1".repeat(19);
    expect(parseBankAccount(max)).toBe(max);
  });

  it("strips whitespace", () => {
    expect(parseBankAccount("1234 5678 9012")).toBe("123456789012");
    expect(parseBankAccount("  1234 5678  ")).toBe("12345678");
  });

  it("strips hyphens", () => {
    expect(parseBankAccount("1234-5678-9012")).toBe("123456789012");
  });

  it("preserves leading zeros (some banks issue them)", () => {
    expect(parseBankAccount("00123456")).toBe("00123456");
  });

  it("rejects too-short", () => {
    expect(parseBankAccount("1234567")).toBeNull(); // 7 digits
  });

  it("rejects too-long", () => {
    expect(parseBankAccount("1".repeat(20))).toBeNull();
  });

  it("rejects non-digit characters", () => {
    expect(parseBankAccount("12345678abc")).toBeNull();
    expect(parseBankAccount("1234.5678")).toBeNull();
  });

  it("rejects null / undefined / empty", () => {
    expect(parseBankAccount(null)).toBeNull();
    expect(parseBankAccount(undefined)).toBeNull();
    expect(parseBankAccount("")).toBeNull();
  });
});


// ---------- formatBankAccount — grouping ----------


describe("formatBankAccount — right-aligned grouping", () => {
  it("groups 8 digits as 4-4", () => {
    expect(formatBankAccount("12345678")).toBe("1234 5678");
  });

  it("groups 9 digits as 1-4-4 (last group always 4)", () => {
    // Cardinal pin: right-aligned. The LEADING group has the
    // remainder (1 digit here), the LAST group always has 4.
    expect(formatBankAccount("123456789")).toBe("1 2345 6789");
  });

  it("groups 11 digits as 3-4-4", () => {
    expect(formatBankAccount("12345678901")).toBe("123 4567 8901");
  });

  it("groups 16 digits as 4-4-4-4", () => {
    expect(formatBankAccount("1234567890123456")).toBe("1234 5678 9012 3456");
  });

  it("groups 19 digits as 3-4-4-4-4", () => {
    expect(formatBankAccount("1234567890123456789")).toBe(
      "123 4567 8901 2345 6789",
    );
  });

  it("groups 12 digits as 4-4-4 (no leading short group)", () => {
    // When the count is a multiple of 4, no leading short group.
    expect(formatBankAccount("123456789012")).toBe("1234 5678 9012");
  });
});


// ---------- formatBankAccount — round-trip + defensive ----------


describe("formatBankAccount", () => {
  it("round-trips already-formatted input", () => {
    expect(formatBankAccount("1234 5678")).toBe("1234 5678");
    expect(formatBankAccount("1234 5678 9012")).toBe("1234 5678 9012");
  });

  it("strips and re-groups input with non-canonical spacing", () => {
    expect(formatBankAccount("12 34 56 78")).toBe("1234 5678");
  });

  it("preserves leading zeros in output", () => {
    expect(formatBankAccount("00123456")).toBe("0012 3456");
  });

  it("returns '' for null / undefined / empty", () => {
    // Chained-render-friendly: caller can do
    // `formatBankAccount(row.account)` without null check.
    expect(formatBankAccount(null)).toBe("");
    expect(formatBankAccount(undefined)).toBe("");
    expect(formatBankAccount("")).toBe("");
  });

  it("returns '' for invalid input", () => {
    expect(formatBankAccount("invalid")).toBe("");
    expect(formatBankAccount("1234567")).toBe(""); // too short
    expect(formatBankAccount("1".repeat(20))).toBe(""); // too long
  });
});


// ---------- bankDisplayName ----------


describe("bankDisplayName", () => {
  it("returns display name for known code", () => {
    expect(bankDisplayName("VCB")).toBe("Vietcombank");
    expect(bankDisplayName("TCB")).toBe("Techcombank");
  });

  it("is case-insensitive on the code", () => {
    expect(bankDisplayName("vcb")).toBe("Vietcombank");
    expect(bankDisplayName("Vcb")).toBe("Vietcombank");
  });

  it("returns null for unknown code", () => {
    expect(bankDisplayName("UNKNOWN")).toBeNull();
    expect(bankDisplayName("XYZ")).toBeNull();
  });

  it("returns null for null / undefined / empty", () => {
    expect(bankDisplayName(null)).toBeNull();
    expect(bankDisplayName(undefined)).toBeNull();
    expect(bankDisplayName("")).toBeNull();
  });
});
