/**
 * Estimate revision number formatter (cycle BBB2, TS half).
 *
 * Estimates accrue revisions over the bidding cycle: the initial
 * estimate is `EST-2026-001`; the first revision (after the
 * estimator updates after a clarification) is `EST-2026-001/r1`;
 * the next is `EST-2026-001/r2`. Today the estimate detail page,
 * the audit row's "estimate.update" formatter, and the PDF
 * export's revision badge format inline with subtly different
 * conventions (one uses `-v2`, another uses `(r2)`). This module
 * is the single source of truth.
 *
 *   PREFIX_LENGTH_MIN / MAX           — 2 / 4
 *   SEQUENCE_LENGTH                   — 3 (zero-padded)
 *   MAX_SEQUENCE / MAX_REVISION       — 999 / 999
 *   RevisionNumber                    — frozen: {prefix, year, sequence, revision}
 *   parseRevisionNumber(input)        — RevisionNumber | null
 *   formatRevisionNumber(rev)         — canonical string
 *   isValidRevisionNumber(input)      — bool
 *
 * Format: `<PREFIX>-<YYYY>-<NNN>` (base) or `<PREFIX>-<YYYY>-<NNN>/r<R>` (revised).
 *   * PREFIX: 2-4 uppercase letters (e.g. `EST`, `CO`, `RFI`).
 *   * YYYY: 4-digit year (2020-2099).
 *   * NNN: 3-digit zero-padded sequence (001-999).
 *   * /rR: optional revision tag, `r` lowercase, 1-999.
 *
 * Pinned invariants:
 *   * Base (`revision=0`) renders WITHOUT `/r0` suffix.
 *   * Revised (`revision>=1`) renders WITH `/rN` suffix (N not padded).
 *   * Year range [2020, 2099] (the codebase pre-dates 2020 only via
 *     migrated legacy projects; post-2099 problems are not ours).
 *   * Sequence MUST be in [1, 999]; sequence=0 → null on parse.
 *   * Revision MUST be in [0, 999]; revision<0 or >999 → null.
 *   * Round-trip: parse(format(rev)) === rev for all valid revs.
 *   * Cross-language byte-for-byte parity with Python half.
 *
 * Pure TS. Mirrors `apps/api/services/format_revision.py`.
 */


export const PREFIX_LENGTH_MIN = 2;
export const PREFIX_LENGTH_MAX = 4;
export const SEQUENCE_LENGTH = 3;
export const MAX_SEQUENCE = 999;
export const MAX_REVISION = 999;
export const MIN_YEAR = 2020;
export const MAX_YEAR = 2099;


export interface RevisionNumber {
  readonly prefix: string;
  readonly year: number;
  readonly sequence: number;
  /** 0 means "base" (no revision suffix). */
  readonly revision: number;
}


// Matches `<PREFIX>-<YYYY>-<NNN>` with optional `/r<R>` tail.
// PREFIX is 2-4 uppercase letters ONLY (no digits — a refactor
// that allowed digits would collide with the year segment).
const REVISION_RE =
  /^([A-Z]{2,4})-(\d{4})-(\d{1,3})(?:\/r(\d{1,3}))?$/;


/** Strip surrounding whitespace + return string or null. */
function clean(input: string | null | undefined): string | null {
  if (input === null || input === undefined) return null;
  const s = input.trim();
  if (!s) return null;
  return s;
}


/**
 * Parse a revision number string.
 *
 * Accepts:
 *   * `EST-2026-001`           → revision=0
 *   * `EST-2026-001/r2`        → revision=2
 *   * `EST-2026-1`             → sequence=1 (non-zero-padded accepted)
 *   * Whitespace around (stripped).
 *
 * Rejects (returns null):
 *   * Lowercase prefix.
 *   * Prefix with digits.
 *   * Sequence 0.
 *   * Revision 0 with explicit `/r0` suffix (canonical form for
 *     "no revision" is OMITTING the suffix, not `/r0`).
 *   * Year outside [2020, 2099].
 *   * Sequence > 999.
 *   * Wrong separator (`_`, `.`).
 */
export function parseRevisionNumber(
  input: string | null | undefined,
): RevisionNumber | null {
  const s = clean(input);
  if (s === null) return null;
  const m = REVISION_RE.exec(s);
  if (m === null) return null;
  const prefix = m[1]!;
  const year = parseInt(m[2]!, 10);
  const sequence = parseInt(m[3]!, 10);
  const revisionStr = m[4];

  if (year < MIN_YEAR || year > MAX_YEAR) return null;
  if (sequence < 1 || sequence > MAX_SEQUENCE) return null;

  let revision = 0;
  if (revisionStr !== undefined) {
    revision = parseInt(revisionStr, 10);
    // Pin: `/r0` is invalid (base form omits the suffix).
    if (revision < 1 || revision > MAX_REVISION) return null;
  }

  return { prefix, year, sequence, revision };
}


/**
 * Format a revision number in canonical form.
 *
 *   * formatRevisionNumber({prefix:"EST",year:2026,sequence:1,revision:0})
 *     → "EST-2026-001"
 *   * formatRevisionNumber({prefix:"EST",year:2026,sequence:1,revision:2})
 *     → "EST-2026-001/r2"
 *
 * Throws RangeError on out-of-range inputs (caller-side bug —
 * unlike parse, format is the formatter's responsibility, so we
 * fail loud rather than silently producing a malformed string).
 */
export function formatRevisionNumber(rev: RevisionNumber): string {
  if (!/^[A-Z]{2,4}$/.test(rev.prefix)) {
    throw new RangeError(`invalid prefix: ${JSON.stringify(rev.prefix)}`);
  }
  if (rev.year < MIN_YEAR || rev.year > MAX_YEAR) {
    throw new RangeError(`year out of range: ${rev.year}`);
  }
  if (rev.sequence < 1 || rev.sequence > MAX_SEQUENCE) {
    throw new RangeError(`sequence out of range: ${rev.sequence}`);
  }
  if (rev.revision < 0 || rev.revision > MAX_REVISION) {
    throw new RangeError(`revision out of range: ${rev.revision}`);
  }
  const seqStr = String(rev.sequence).padStart(SEQUENCE_LENGTH, "0");
  const base = `${rev.prefix}-${rev.year}-${seqStr}`;
  if (rev.revision === 0) return base;
  return `${base}/r${rev.revision}`;
}


/** True iff `parseRevisionNumber(input)` returns non-null. */
export function isValidRevisionNumber(
  input: string | null | undefined,
): boolean {
  return parseRevisionNumber(input) !== null;
}


/**
 * Return the next revision: increment `revision` by 1.
 *
 *   * nextRevision({...rev, revision:0}) → revision=1
 *   * nextRevision({...rev, revision:2}) → revision=3
 *
 * Throws RangeError if at MAX_REVISION (overflow).
 */
export function nextRevision(rev: RevisionNumber): RevisionNumber {
  if (rev.revision >= MAX_REVISION) {
    throw new RangeError(
      `revision exhausted at ${MAX_REVISION}`,
    );
  }
  return { ...rev, revision: rev.revision + 1 };
}
