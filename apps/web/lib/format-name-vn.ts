/**
 * Vietnamese name formatter (cycle QQ2, TS half).
 *
 * Vietnamese naming convention: family → middle → given (Họ →
 * Tên đệm → Tên), opposite of Western "first last" order. Today
 * the user profile card, the audit row actor display, and the
 * RFQ contact line each format inline with subtly different
 * Western/VN ordering. This module is the single source of
 * truth.
 *
 *   formatNameVN(name, format)  — formatted string
 *   VietnameseName              — interface: (family, middle, given)
 *   NameFormat                  — "full" | "given" | "western" | "initials"
 *
 * Pinned invariants:
 *   * Default "full" follows VN convention: family-first.
 *   * "western" reverses to "given family" (middle dropped, as
 *     Western convention often does).
 *   * "initials" includes ALL three parts (family + middle + given).
 *   * Empty middle gracefully omitted from full / initials.
 *   * Whitespace trimmed per segment.
 *   * Empty family → empty output (family is required —
 *     defends against accidental "given-only" output that
 *     looks like a Western first name).
 *   * Cross-language byte-for-byte parity.
 */


export type NameFormat = "full" | "given" | "western" | "initials";


export interface VietnameseName {
  /** Họ (family / surname). Required. */
  family: string;
  /** Tên đệm (middle name). Optional, may be multi-word. */
  middle: string;
  /** Tên (given name). Optional. */
  given: string;
}


/** First-letter initials for each space-separated word. */
function _initials(parts: readonly string[]): string {
  let result = "";
  for (const part of parts) {
    for (const word of part.split(/\s+/)) {
      if (word) {
        result += word.charAt(0).toUpperCase();
      }
    }
  }
  return result;
}


/**
 * Format a Vietnamese name in the requested style.
 *
 *   * formatNameVN({family: "Nguyễn", middle: "Văn", given: "Anh"}, "full")
 *       → "Nguyễn Văn Anh"     (VN convention)
 *   * formatNameVN(..., "given")
 *       → "Anh"
 *   * formatNameVN(..., "western")
 *       → "Anh Nguyễn"         (Western convention, middle dropped)
 *   * formatNameVN(..., "initials")
 *       → "NVA"
 *
 * Empty family → "" (cardinal pin: family is required).
 */
export function formatNameVN(
  name: VietnameseName,
  format: NameFormat = "full",
): string {
  const family = name.family.trim();
  if (!family) return "";

  const middle = name.middle.trim();
  const given = name.given.trim();

  if (format === "given") {
    return given;
  }

  if (format === "western") {
    // Given first, family last. Middle dropped.
    return given ? `${given} ${family}` : family;
  }

  if (format === "initials") {
    const parts: string[] = [family];
    if (middle) parts.push(middle);
    if (given) parts.push(given);
    return _initials(parts);
  }

  // Default: "full" — VN convention: family → middle → given.
  const parts: string[] = [family];
  if (middle) parts.push(middle);
  if (given) parts.push(given);
  return parts.join(" ");
}
