/**
 * Frontend pagination helper (cycle FF3, TS-only).
 *
 * Given `currentPage`, `totalPages`, and an optional
 * `siblingCount`, return an array of page tokens to render
 * page-number buttons. Numbers are page integers; the literal
 * "ellipsis" represents a gap.
 *
 *   buildPageRange(current, total, siblingCount)  — PageToken[]
 *
 * Used by:
 *   * /settings/audit
 *   * /admin/webhook-deliveries
 *   * /admin/webhook-deliveries/dead-letter
 *   * /settings/members (org-member list)
 *
 * Today each of those pages reimplements pagination inline,
 * with subtly different ellipsis logic (one shows a single
 * ellipsis when there are exactly 2 hidden pages; another
 * shows ellipsis only when ≥3 hidden). This module is the
 * single source of truth.
 *
 * Frontend-only — no Python counterpart since pagination is
 * a render concern, not an API contract.
 *
 * Pinned invariants (see test):
 *   * `totalPages = 1` returns `[1]` (no ellipsis).
 *   * `currentPage` is ALWAYS in the output.
 *   * First and last pages are ALWAYS in the output.
 *   * Ellipsis only when there's a strict gap (>1) between
 *     adjacent rendered numbers.
 *   * No consecutive ellipses.
 *   * `currentPage` clamps into `[1, totalPages]`.
 */


/** A page token: either a 1-indexed page number or the literal
 *  "ellipsis" sentinel. The consumer renders numbers as buttons
 *  and "ellipsis" as a non-clickable separator. */
export type PageToken = number | "ellipsis";


/**
 * Build a page-number range for rendering pagination.
 *
 *   * buildPageRange(1, 1)        → [1]
 *   * buildPageRange(1, 5)        → [1, 2, "ellipsis", 5]
 *   * buildPageRange(3, 5)        → [1, 2, 3, 4, 5]
 *   * buildPageRange(5, 20)       → [1, "ellipsis", 4, 5, 6, "ellipsis", 20]
 *   * buildPageRange(5, 20, 0)    → [1, "ellipsis", 5, "ellipsis", 20]
 *   * buildPageRange(0, 5)        → same as buildPageRange(1, 5)  (clamp)
 *   * buildPageRange(99, 5)       → same as buildPageRange(5, 5)  (clamp)
 *   * buildPageRange(1, 0)        → []
 */
export function buildPageRange(
  currentPage: number,
  totalPages: number,
  siblingCount: number = 1,
): PageToken[] {
  if (totalPages <= 0) return [];
  if (totalPages === 1) return [1];

  // Clamp current page into [1, totalPages].
  const cur = Math.max(1, Math.min(currentPage, totalPages));

  // Always render: 1, totalPages, current ± siblingCount.
  const renderSet = new Set<number>([1, totalPages, cur]);
  for (let i = 1; i <= siblingCount; i++) {
    if (cur - i >= 1) renderSet.add(cur - i);
    if (cur + i <= totalPages) renderSet.add(cur + i);
  }

  const numbers = Array.from(renderSet).sort((a, b) => a - b);

  // Insert "ellipsis" between non-adjacent numbers.
  const result: PageToken[] = [];
  for (let i = 0; i < numbers.length; i++) {
    result.push(numbers[i]!);
    if (i < numbers.length - 1 && numbers[i + 1]! - numbers[i]! > 1) {
      result.push("ellipsis");
    }
  }
  return result;
}
