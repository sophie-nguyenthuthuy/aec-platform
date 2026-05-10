/**
 * Frontend table sort helper (cycle KK3, TS-only).
 *
 * Multi-column stable sort. Today the audit table, deliveries
 * table, dead-letter table, and member list each implement
 * sorting inline with subtly different null-handling and
 * stability guarantees. This module is the single source of
 * truth.
 *
 *   sortRows(rows, sortKeys)  — returns a NEW sorted array
 *
 * Frontend-only — sorting is a render concern, no API
 * counterpart.
 *
 * Pinned invariants:
 *   * Input array NOT mutated (returns a new array).
 *   * Stable: rows tied on all sort keys preserve input order.
 *   * Null/undefined values sort to END regardless of direction
 *     (defensive — defends against `null` accidentally sorting
 *     to "before all" in JS string comparisons).
 *   * Empty `sortKeys` returns input copy unchanged.
 *   * Multi-column tie-break: secondary key only applied on
 *     primary tie.
 *
 * The function double-stabilizes via index-pair comparison
 * (even though modern JS engines guarantee stable sort, pin so
 * a refactor to a non-stable algorithm can't slip past).
 */


export type SortDirection = "asc" | "desc";


export interface SortKey<T> {
  key: keyof T;
  direction: SortDirection;
}


/**
 * Sort `rows` by the given multi-column `sortKeys`.
 *
 * Returns a NEW array. The input is not mutated.
 *
 *   * sortRows([], [])                → []
 *   * sortRows(rows, [])              → rows.slice()  (copy, no sort)
 *   * sortRows(rows, [{key, "asc"}])  → ascending by key
 *   * sortRows(rows, [{a, "asc"}, {b, "desc"}])
 *       → primary asc by `a`, secondary desc by `b` on tie
 */
export function sortRows<T>(
  rows: readonly T[],
  sortKeys: readonly SortKey<T>[],
): T[] {
  if (sortKeys.length === 0) {
    return rows.slice();
  }

  // Pair each row with its original index for stability.
  const indexed = rows.map((row, i) => ({ row, i }));

  indexed.sort((a, b) => {
    for (const { key, direction } of sortKeys) {
      const va = a.row[key];
      const vb = b.row[key];

      // Null/undefined → END regardless of direction.
      const aNull = va === null || va === undefined;
      const bNull = vb === null || vb === undefined;
      if (aNull && bNull) continue;
      if (aNull) return 1;  // a goes after b
      if (bNull) return -1; // b goes after a

      let cmp = 0;
      if (va < vb) cmp = -1;
      else if (va > vb) cmp = 1;

      if (cmp !== 0) {
        return direction === "desc" ? -cmp : cmp;
      }
      // Tie on this key — fall through to next sortKey.
    }
    // All keys tied — preserve original order (stability).
    return a.i - b.i;
  });

  return indexed.map(({ row }) => row);
}
