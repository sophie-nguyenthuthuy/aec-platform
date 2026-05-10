/**
 * VN bank account number formatter (cycle HH2, TS half).
 *
 * Vietnamese bank account numbers are 8-19 digits, conventionally
 * displayed in 4-digit groups aligned from the right. Today the
 * org payment-settings page, the invoice template, and the audit
 * row's bank-account-impact detector each format inline with
 * subtly different grouping (one uses 3-digit, another no grouping).
 * This module is the single source of truth.
 *
 *   formatBankAccount(input)   — "1234 5678 9012 3456"
 *   parseBankAccount(input)    — canonical digits or null
 *   bankDisplayName(code)      — registry lookup
 *   VN_BANKS                   — closed bank-code → display name
 *
 * Convention:
 *   * 8-19 digits accepted (legacy 8-digit accounts still active
 *     at older banks; modern accounts up to 19).
 *   * Right-aligned 4-digit grouping: the LAST group has 4 chars,
 *     the FIRST group has 1-4 chars depending on total length.
 *   * Leading zeros are PRESERVED (some VN banks issue accounts
 *     with leading zeros — pin so a refactor that strips them
 *     doesn't silently lose precision).
 *
 * Pure TS. Mirrors `apps/api/services/format_bank_account.py`.
 */


/** Closed registry of major Vietnamese banks. Bank codes are
 *  3-4 letter abbreviations (often used in transfer slips and
 *  the bank-prefix dropdown). Pin so a refactor that adds a
 *  bank without consulting the BIN registry surfaces here. */
export const VN_BANKS = {
  VCB: "Vietcombank",
  TCB: "Techcombank",
  BIDV: "BIDV",
  ACB: "ACB",
  MB: "MB Bank",
  VIB: "VIB",
  STB: "Sacombank",
  TPB: "TPBank",
  OCB: "OCB",
  HDB: "HDBank",
  EXB: "Eximbank",
  VPB: "VPBank",
} as const;


export type VNBankCode = keyof typeof VN_BANKS;


/** Min length — legacy 8-digit accounts at older banks. */
export const MIN_BANK_ACCOUNT_LENGTH = 8;


/** Max length — modern long-form accounts. */
export const MAX_BANK_ACCOUNT_LENGTH = 19;


/**
 * Parse a bank account string and return canonical digits or null.
 *
 * Accepts whitespace and hyphens (stripped). Rejects:
 *   * null / undefined / empty
 *   * non-digit characters (after stripping)
 *   * length outside [8, 19]
 */
export function parseBankAccount(
  input: string | null | undefined,
): string | null {
  if (input === null || input === undefined || input === "") return null;
  const cleaned = input.replace(/[\s\-]/g, "");
  if (!cleaned) return null;
  if (!/^\d+$/.test(cleaned)) return null;
  if (cleaned.length < MIN_BANK_ACCOUNT_LENGTH) return null;
  if (cleaned.length > MAX_BANK_ACCOUNT_LENGTH) return null;
  return cleaned;
}


/**
 * Format a bank account in canonical 4-digit-grouped form.
 *
 *   * formatBankAccount("12345678")            → "1234 5678"
 *   * formatBankAccount("123456789")           → "1 2345 6789"
 *   * formatBankAccount("12345678901")         → "123 4567 8901"
 *   * formatBankAccount("1234567890123456")    → "1234 5678 9012 3456"
 *   * formatBankAccount("1234 5678")           → "1234 5678"  (round-trip)
 *   * formatBankAccount(null)                  → ""
 *   * formatBankAccount("invalid")             → ""
 *
 * Right-aligned: the LAST group always has 4 digits; the FIRST
 * group has 1-4 depending on total length. Pin so a refactor to
 * left-aligned (LAST group having the remainder) would surface
 * here — left-aligned is unconventional in VN finance UIs.
 */
export function formatBankAccount(
  input: string | null | undefined,
): string {
  const cleaned = parseBankAccount(input);
  if (cleaned === null) return "";
  const groups: string[] = [];
  let i = cleaned.length;
  while (i > 0) {
    const start = Math.max(0, i - 4);
    groups.unshift(cleaned.slice(start, i));
    i -= 4;
  }
  return groups.join(" ");
}


/**
 * Look up a bank's display name by code (case-insensitive).
 *
 * Returns null for unknown codes. Used by the bank-prefix
 * dropdown to render `"VCB — Vietcombank"`.
 */
export function bankDisplayName(
  code: string | null | undefined,
): string | null {
  if (!code) return null;
  const upper = code.toUpperCase();
  if (upper in VN_BANKS) {
    return VN_BANKS[upper as VNBankCode];
  }
  return null;
}
