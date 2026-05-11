/**
 * Audit search highlighter (cycle WW1, TS half).
 *
 * Given free-text search terms + a text body, return non-
 * overlapping spans of matches for UI highlighting in the
 * audit list note column, the search-results page, and the
 * Slack alert digest excerpt builder.
 *
 *   findMatches(text, terms)  — readonly Match[]
 *   Match                     — { start, end }
 *
 * Composes with II1's `parse_search_query.free_text` (caller
 * passes `query.free_text` as `terms`).
 *
 * Pure TS. Mirrors `apps/api/services/highlight_matches.py`.
 *
 * Pinned invariants:
 *   * Case-insensitive matching.
 *   * Non-overlapping spans (greedy left-to-right; on tie,
 *     longer wins).
 *   * Empty / null `text` or empty `terms` → [].
 *   * Whitespace-only term skipped.
 *   * Deterministic order: matches in document order.
 *   * Cross-language byte-for-byte parity.
 */


export interface Match {
  /** Inclusive start index. */
  start: number;
  /** Exclusive end index. */
  end: number;
}


/**
 * Find non-overlapping match spans for any of `terms` in `text`.
 *
 * Returns a list of `{start, end}` matches in document order.
 * Indexes refer to the ORIGINAL `text` (NOT the lowercased
 * version) — caller can slice directly.
 *
 *   * findMatches("Hello World", ["hello"])      → [{start: 0, end: 5}]
 *   * findMatches("foo bar foo", ["foo"])        → [{0,3}, {8,11}]
 *   * findMatches("aaaa", ["aa"])                → [{0,2}, {2,4}]   (greedy)
 *   * findMatches("hello", ["hello", "ell"])     → [{0,5}]          (longer wins)
 *   * findMatches(null, [...])                   → []
 *   * findMatches("text", [])                    → []
 */
export function findMatches(
  text: string | null | undefined,
  terms: readonly string[],
): readonly Match[] {
  if (!text || terms.length === 0) return [];

  const textLower = text.toLowerCase();
  const candidates: Array<[number, number]> = [];

  for (const term of terms) {
    if (!term) continue;
    const t = term.trim().toLowerCase();
    if (!t) continue;
    let idx = 0;
    while (idx < textLower.length) {
      const found = textLower.indexOf(t, idx);
      if (found < 0) break;
      candidates.push([found, found + t.length]);
      // Step forward by 1 to find overlapping candidates;
      // greedy resolution below picks non-overlapping.
      idx = found + 1;
    }
  }

  if (candidates.length === 0) return [];

  // Sort: start ASC, length DESC (longer wins on tie at same start).
  candidates.sort((a, b) => {
    if (a[0] !== b[0]) return a[0] - b[0];
    return b[1] - b[0] - (a[1] - a[0]);
  });

  // Greedy non-overlapping selection.
  const result: Match[] = [];
  let lastEnd = 0;
  for (const [start, end] of candidates) {
    if (start >= lastEnd) {
      result.push({ start, end });
      lastEnd = end;
    }
  }

  return result;
}
