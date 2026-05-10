/**
 * Enum coalescer (cycle RR1, TS half).
 *
 * Match a user input against a canonical choices set via
 * case-insensitive + whitespace-tolerant lookup. Today the
 * status filter chip handler, role-lookup form, and MIME
 * category resolver each implement inline lookups with subtly
 * different case-handling. This module is the single source
 * of truth.
 *
 *   coalesceEnum(input, choices, defaultValue)  — canonical or default
 *
 * Pure TS. Mirrors `apps/api/services/enum_coalesce.py`.
 *
 * Pinned invariants:
 *   * Exact (case-sensitive) match preferred over case-insensitive.
 *     Pin so a refactor that lowercases first doesn't lose
 *     case-distinction in choices that legitimately differ
 *     (rare — but pin defensively).
 *   * Whitespace stripped on input AND each choice (so caller
 *     can pass choices with internal spaces if needed).
 *   * Empty / null input → default.
 *   * Empty choices → default (not an error).
 *   * First match wins (input order of choices).
 *   * Cross-language byte-for-byte parity.
 */


/**
 * Match `input` against `choices` and return the canonical form,
 * or `defaultValue` if no match.
 *
 *   * coalesceEnum("open", ["open", "closed"])      → "open"
 *   * coalesceEnum("OPEN", ["open", "closed"])      → "open"  (case-insensitive)
 *   * coalesceEnum("  open  ", ["open"])            → "open"  (whitespace strip)
 *   * coalesceEnum("nope", ["open"], "fallback")    → "fallback"
 *   * coalesceEnum(null, ["open"])                  → null
 *   * coalesceEnum("open", [])                      → null
 */
export function coalesceEnum<T extends string>(
  input: string | null | undefined,
  choices: readonly T[],
  defaultValue: T | null = null,
): T | null {
  if (input === null || input === undefined) return defaultValue;
  const s = input.trim();
  if (!s) return defaultValue;
  if (choices.length === 0) return defaultValue;

  // Exact (case-sensitive) match first — pin so a choices set
  // that has both `Open` and `OPEN` (rare) returns the exact
  // one when input matches exactly.
  for (const choice of choices) {
    if (choice === s) return choice;
  }

  // Case-insensitive fallback. Strip whitespace from each choice
  // too in case the canonical set has internal spaces.
  const sLower = s.toLowerCase();
  for (const choice of choices) {
    if (choice.trim().toLowerCase() === sLower) return choice;
  }

  return defaultValue;
}
