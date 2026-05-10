/**
 * Vietnamese phone number formatter (cycle BB2, TS half).
 *
 * Vietnamese mobile numbers: country code +84, 9-digit national
 * number, leading 0 in domestic form. Mobile prefixes (the digit
 * after the leading 0 / +84) are restricted to {3, 5, 7, 8, 9}
 * per the Ministry of Information & Communications 2018 reorg.
 *
 *   formatPhoneVN(input, format)  — render in one of three forms
 *   parsePhoneVN(input)           — canonical E.164 for storage
 *   isValidVNMobile(input)        — bool
 *
 * Today the org member, RFQ contact, and notification preference
 * views each render phones inline with subtly different rules.
 * This module is the single source of truth.
 *
 * Pure TS, no React, no libphonenumber dep. Mirrors
 * `apps/api/services/format_phone_vn.py`.
 *
 * Display formats:
 *   * "national"      → "0901 234 567"     (4-3-3, default)
 *   * "international" → "+84 90 123 4567"  (2-3-4 after +84)
 *   * "e164"          → "+84901234567"     (no separators)
 *
 * Out of scope: landlines (8-digit area-code form). Notification
 * preferences and member contacts are mobile-only.
 */


/** Mobile prefix allowlist — first digit after the leading 0
 *  (or after +84). Per VN MIC 2018 reorg. Pin so a refactor
 *  that adds e.g. "1" silently broadens the allowlist. */
export const VN_MOBILE_PREFIXES: ReadonlySet<string> = new Set([
  "3", "5", "7", "8", "9",
]);


export type PhoneFormat = "national" | "international" | "e164";


/** Strip whitespace, hyphens, dots, and parentheses from a
 *  user-typed phone string. Leading + is preserved. */
function _clean(input: string): string {
  return input.replace(/[\s\-().]/g, "");
}


/** Extract the 9-digit national number from a cleaned input,
 *  or null if invalid. The leading 0 / +84 / 84 is stripped. */
function _extract9Digits(cleaned: string): string | null {
  let rest: string;
  if (cleaned.startsWith("+84")) {
    rest = cleaned.slice(3);
  } else if (cleaned.startsWith("84") && cleaned.length === 11) {
    // "84xxxxxxxxx" — 11 chars total, no leading + but length
    // matches country-coded form. Disambiguate from a national
    // number starting with 84 (which would be invalid anyway —
    // mobile prefixes don't include 8 followed by 4).
    rest = cleaned.slice(2);
  } else if (cleaned.startsWith("0")) {
    rest = cleaned.slice(1);
  } else {
    return null;
  }
  if (rest.length !== 9) return null;
  if (!/^\d{9}$/.test(rest)) return null;
  if (!VN_MOBILE_PREFIXES.has(rest[0])) return null;
  return rest;
}


/**
 * Parse a phone string and return the canonical E.164 form
 * (`+84XXXXXXXXX`), or null if invalid.
 *
 * Accepts:
 *   * "0901234567"        → "+84901234567"
 *   * "+84901234567"      → "+84901234567"
 *   * "84901234567"       → "+84901234567"
 *   * "+84 90 123 4567"   → "+84901234567"
 *   * "0901 234 567"      → "+84901234567"
 *
 * Rejects:
 *   * Empty / null / undefined → null
 *   * Wrong length            → null
 *   * Non-mobile prefix       → null (e.g. "0123456789" — '1' isn't allowed)
 *   * Non-digit chars after cleaning → null
 */
export function parsePhoneVN(input: string | null | undefined): string | null {
  if (input === null || input === undefined || input === "") return null;
  const cleaned = _clean(input);
  if (cleaned === "") return null;
  const rest = _extract9Digits(cleaned);
  if (rest === null) return null;
  return `+84${rest}`;
}


/** True iff `parsePhoneVN(input)` would return a non-null E.164. */
export function isValidVNMobile(input: string | null | undefined): boolean {
  return parsePhoneVN(input) !== null;
}


/**
 * Format a phone string in one of three display forms.
 *
 * Default is "national" since that's the most common form in
 * Vietnamese UIs (the leading 0 is universally recognised).
 *
 * Invalid input → "" (no-op for chained renderers — calling
 * code can do `formatPhoneVN(member.phone)` without a null check).
 */
export function formatPhoneVN(
  input: string | null | undefined,
  format: PhoneFormat = "national",
): string {
  const e164 = parsePhoneVN(input);
  if (e164 === null) return "";
  const digits = e164.slice(3); // 9 digits after "+84"
  switch (format) {
    case "e164":
      return e164;
    case "international":
      // 2-3-4 grouping after "+84 ".
      return `+84 ${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5)}`;
    case "national":
    default:
      // 4-3-3 grouping with leading 0.
      return `0${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`;
  }
}
