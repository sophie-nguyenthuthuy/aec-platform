/**
 * Audit diff summarization (cycle X1, TS half).
 *
 * `summarizeDiff(before, after)` produces a compact one-line render
 * of "what changed" between two audit-row snapshots. Used in three
 * places today (P2's `/settings/audit`, S3's project audit page,
 * V1's pinned section); each had a near-identical 20-line
 * implementation that drifted between rewrites. This module is
 * the source of truth.
 *
 * Output shape — at most TWO key changes joined with " · ":
 *
 *   "role: member → admin"
 *   "role: member → admin · status: draft → approved"
 *
 * Two-key cap is deliberate: the audit row also renders an
 * action chip + actor + timestamp on the same line. Three+ key
 * diffs would push the row past one visual line.
 *
 * Symbols:
 *   * `→` — value changed
 *   * `∅ → X` — key was absent in `before` (added)
 *   * `X → ∅` — key was absent in `after` (removed)
 *
 * Equality: `before[k] !== after[k]` (strict inequality). Object
 * values render as JSON to keep the line bounded — operators
 * curious about the full nested diff click to expand.
 *
 * Pure function, no React, no I/O. Drop-in for both row components.
 */


export interface DiffSummary {
  /** The compact text rendering. Empty string when no changes. */
  text: string;
  /** Total number of differing keys. Frontend uses this to render
   *  "+ 5 more" when the cap was exceeded. */
  totalChanges: number;
}


/** Maximum keys included in the inline summary. Beyond this the
 *  caller renders "+ N more" so the row stays one line. */
export const SUMMARY_KEY_CAP = 2;


/**
 * Walk the union of keys in `before` and `after`, emit one entry
 * per differing key (capped at `SUMMARY_KEY_CAP`).
 *
 * Object-typed values get JSON.stringified so a nested diff
 * doesn't blow up the line. Strings, numbers, booleans, null all
 * render as `String(v)`.
 */
export function summarizeDiff(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): DiffSummary {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const parts: string[] = [];
  let totalChanges = 0;
  for (const k of keys) {
    const b = before[k];
    const a = after[k];
    if (Object.is(b, a)) continue;
    // Both undefined would have been filtered above (Object.is(undef, undef) = true).
    totalChanges += 1;
    if (parts.length < SUMMARY_KEY_CAP) {
      parts.push(`${k}: ${formatValue(b)} → ${formatValue(a)}`);
    }
  }
  return { text: parts.join(" · "), totalChanges };
}


/**
 * Format one value for inline rendering.
 *
 *   * undefined → ∅ (the "absent" symbol)
 *   * null      → "null" — distinct from absent; null is a value
 *   * objects   → JSON.stringify (one-liner)
 *   * everything else → String(...)
 *
 * The ∅ vs "null" distinction matters for governance reading: a
 * field that was absent before AND set to null after still records
 * a change (`∅ → null`). The full audit-row expansion shows the
 * raw values — the summary tells you which keys to look at.
 */
export function formatValue(v: unknown): string {
  if (v === undefined) return "∅";
  if (v === null) return "null";
  if (typeof v === "object") {
    try {
      return JSON.stringify(v);
    } catch {
      // Circular ref or some exotic shape — fall back to a sentinel
      // rather than crashing the row render.
      return "[object]";
    }
  }
  return String(v);
}
