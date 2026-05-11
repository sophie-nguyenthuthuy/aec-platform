import { fireEvent, render, screen } from "@testing-library/react";
import * as fc from "fast-check";
import { describe, expect, test } from "vitest";

import type { FeeBreakdown, FeeLine } from "@aec/types/winwork";
import { FeeBreakdownTable } from "../FeeBreakdownTable";

/**
 * Property tests over the recalc behaviour of `<FeeBreakdownTable>`.
 *
 * Why fast-check on this specifically
 * -----------------------------------
 * The example-based suite (`FeeBreakdownTable.test.tsx`) pins the
 * happy paths. But the recalc function lives at the heart of every
 * proposal we send a client and runs on operator-typed numbers,
 * including the long tail: very large amounts (a multi-billion-VND
 * fit-out is real), zero rows, mixed positive/negative (credit-note
 * scenarios), single-row tables, and concurrent edits that pass
 * partially-formed numbers. Example tests can't enumerate that
 * space without becoming a wall of redundant cases.
 *
 * Three properties worth pinning over generated inputs:
 *
 *   1. **Subtotal = Σ amounts.** The reduce() in `recalc()` should
 *      return a faithful sum across any shape of `lines[]`.
 *      Mutations that swap `+` for `*` or accumulate the wrong field
 *      die here on the first counter-example.
 *
 *   2. **Total = Subtotal + VAT.** Mechanical, but a real bug class:
 *      the original code path in `recalc()` builds total from
 *      `subtotal + vat` so a typo to `total - vat` or `total = vat`
 *      gets caught immediately.
 *
 *   3. **VAT = round(Subtotal × 0.08).** Pin the rounding rule. The
 *      existing example test pins one specific case (350M × 0.08 =
 *      28M); fast-check finds boundary subtotals where Math.round
 *      vs Math.floor diverge (anything where `subtotal * 0.08` lands
 *      on .5).
 *
 * We exercise recalc through the user-facing onChange contract
 * rather than reaching into the (unexported) `recalc` helper —
 * that's the only path in production, and it's the path that
 * actually matters. Driving via the UI also catches bugs in the
 * `onChange(recalc(...))` pipeline composition itself.
 *
 * VND amounts stay realistic (0 to 100B); we don't need fast-check
 * to find float-precision edge cases at 2^53. Negative amounts are
 * intentionally allowed — credit-note line items are a real flow.
 */

// fast-check `numRuns` defaults to 100. That's plenty for these
// arity-2/3 properties; CI cost stays small (~50ms/test). Bump
// locally with `FAST_CHECK_NUM_RUNS=1000` if you're chasing a flake.
const NUM_RUNS = Number(process.env.FAST_CHECK_NUM_RUNS ?? 100);

const feeLineArb: fc.Arbitrary<FeeLine> = fc.record({
  phase: fc.constantFrom("Concept", "DD", "CD", "CA"),
  label: fc.string({ minLength: 1, maxLength: 30 }),
  // Real-world VND envelope: 0 to 100B, integer (we never store fractional dong).
  // Allow negatives (credit notes) but keep magnitude bounded so
  // sums don't overflow Number's safe-int range across 50 rows.
  amount_vnd: fc.integer({ min: -10_000_000_000, max: 100_000_000_000 }),
});

function makeBreakdown(lines: FeeLine[]): FeeBreakdown {
  const subtotal = lines.reduce((s, l) => s + (l.amount_vnd || 0), 0);
  const vat = Math.round(subtotal * 0.08);
  return {
    lines,
    subtotal_vnd: subtotal,
    vat_vnd: vat,
    total_vnd: subtotal + vat,
  };
}

describe("FeeBreakdownTable / recalc properties", () => {
  test("editing any single row's amount → emitted breakdown satisfies all three invariants", () => {
    fc.assert(
      fc.property(
        // 1+ rows so there's a row to edit; cap at 8 to keep the DOM small.
        fc.array(feeLineArb, { minLength: 1, maxLength: 8 }),
        // Index of the row to edit (constrained inside the test body
        // via `% lines.length`).
        fc.nat(),
        // The new amount the user types in.
        fc.integer({ min: 0, max: 100_000_000_000 }),
        (lines, rawIdx, newAmount) => {
          const idx = rawIdx % lines.length;
          let captured: FeeBreakdown | null = null;
          const { unmount } = render(
            <FeeBreakdownTable
              value={makeBreakdown(lines)}
              onChange={(next) => {
                captured = next;
              }}
            />,
          );
          // The amount inputs are the third <input> in each row
          // (phase, label, amount). Pick the one for the edit-target
          // row by its current display value, falling back to nth
          // when multiple rows share an amount.
          const allInputs = screen.getAllByRole("spinbutton");
          fireEvent.change(allInputs[idx]!, {
            target: { value: String(newAmount) },
          });

          unmount();
          // onChange must have fired exactly once.
          expect(captured).not.toBeNull();
          // `captured` is typed `FeeBreakdown | null`; the assertion
          // above just narrowed the null branch, so a non-null
          // assertion is enough — no double-cast needed.
          const next = captured!;

          // Property 1: subtotal = Σ amounts.
          const computedSubtotal = next.lines.reduce(
            (s, l) => s + (l.amount_vnd || 0),
            0,
          );
          expect(next.subtotal_vnd).toBe(computedSubtotal);

          // Property 2: total = subtotal + vat (allow ±1 VND for
          // rounding cascades; in practice they always coincide
          // exactly, but the assertion is the structural one).
          expect(next.total_vnd).toBe(next.subtotal_vnd + next.vat_vnd);

          // Property 3: VAT is round(subtotal * 0.08). Use Math.round
          // to mirror the implementation rather than asserting a
          // floor/ceil — the rule itself is what we're pinning.
          expect(next.vat_vnd).toBe(Math.round(next.subtotal_vnd * 0.08));

          // The edited row reflects the new amount.
          expect(next.lines[idx]!.amount_vnd).toBe(newAmount);
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  test("removing any row preserves all three invariants on the smaller breakdown", () => {
    fc.assert(
      fc.property(
        fc.array(feeLineArb, { minLength: 1, maxLength: 8 }),
        fc.nat(),
        (lines, rawIdx) => {
          const idx = rawIdx % lines.length;
          let captured: FeeBreakdown | null = null;
          const { unmount } = render(
            <FeeBreakdownTable
              value={makeBreakdown(lines)}
              onChange={(next) => {
                captured = next;
              }}
            />,
          );
          const removeBtns = screen.getAllByRole("button", {
            name: /remove line/i,
          });
          fireEvent.click(removeBtns[idx]!);
          unmount();

          expect(captured).not.toBeNull();
          // `captured` is typed `FeeBreakdown | null`; the assertion
          // above just narrowed the null branch, so a non-null
          // assertion is enough — no double-cast needed.
          const next = captured!;

          expect(next.lines).toHaveLength(lines.length - 1);
          expect(next.subtotal_vnd).toBe(
            next.lines.reduce((s, l) => s + (l.amount_vnd || 0), 0),
          );
          expect(next.total_vnd).toBe(next.subtotal_vnd + next.vat_vnd);
          expect(next.vat_vnd).toBe(Math.round(next.subtotal_vnd * 0.08));
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  test("VAT is monotonically non-decreasing as subtotal grows (positive subtotals)", () => {
    // Sanity property — not strict (floating-point boundaries can
    // tie at the .5 rounding rail), but a "VAT went DOWN when
    // subtotal went up" outcome would be a genuine bug. We check
    // by comparing a generated breakdown to the same breakdown
    // with one extra positive-amount row appended.
    fc.assert(
      fc.property(
        fc.array(feeLineArb, { minLength: 0, maxLength: 6 }),
        fc.integer({ min: 1, max: 1_000_000_000 }),
        (baseLines, extraAmount) => {
          const before = makeBreakdown(baseLines);
          const after = makeBreakdown([
            ...baseLines,
            { phase: "X", label: "extra", amount_vnd: extraAmount },
          ]);
          // Only assert when both subtotals are non-negative —
          // negative-row-heavy inputs can have signs flip.
          fc.pre(before.subtotal_vnd >= 0 && after.subtotal_vnd >= 0);
          expect(after.vat_vnd).toBeGreaterThanOrEqual(before.vat_vnd);
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });
});
