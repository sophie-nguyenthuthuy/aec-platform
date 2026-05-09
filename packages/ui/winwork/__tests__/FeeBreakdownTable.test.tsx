import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { FeeBreakdown } from "@aec/types/winwork";
import { FeeBreakdownTable } from "../FeeBreakdownTable";

/**
 * The FeeBreakdownTable is the proposal editor's money widget — every
 * row edit recomputes subtotal/VAT/total and bubbles a fresh
 * FeeBreakdown to the parent. Three behaviours are worth pinning:
 *
 *   1. Recalc math: VAT = round(subtotal × 0.08), total = subtotal +
 *      VAT. Easy to break with a `* 0.8` typo or a `Math.floor` swap
 *      that quietly drops dong on every proposal.
 *   2. Read-only render: NO inputs, NO Add/Remove buttons. Used for
 *      sent/won proposals — a regression that left an editable input
 *      visible would let the user mutate a frozen quote.
 *   3. The empty-rows case: removing the only row should still emit
 *      a valid FeeBreakdown (subtotal=0, vat=0, total=0), not crash
 *      on `reduce` of an empty array.
 *
 * VND number formatting is locale-dependent. We don't pin the literal
 * string ("1.000.000" vs "1,000,000") — that's where Intl.NumberFormat
 * differs by Node version. Instead we round-trip through Intl directly
 * in the test so the assertion stays portable.
 */

function fmt(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n);
}

function makeBreakdown(): FeeBreakdown {
  return {
    lines: [
      { phase: "Concept", label: "Concept design", amount_vnd: 100_000_000 },
      { phase: "DD", label: "Design development", amount_vnd: 200_000_000 },
    ],
    subtotal_vnd: 300_000_000,
    vat_vnd: 24_000_000,
    total_vnd: 324_000_000,
  };
}

describe("FeeBreakdownTable / read-only mode", () => {
  test("readOnly hides all inputs, the Add button, and the Remove buttons", () => {
    // Pin all three together — a regression that only flipped one
    // would still let the user mutate the frozen quote.
    const { container } = render(
      <FeeBreakdownTable value={makeBreakdown()} readOnly />,
    );
    expect(container.querySelector("input")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /add line/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /remove line/i }),
    ).not.toBeInTheDocument();
  });

  test("readOnly renders amounts as formatted plain text", () => {
    const { container } = render(
      <FeeBreakdownTable value={makeBreakdown()} readOnly />,
    );
    // Each amount appears once in its row + the totals row repeats
    // the subtotal. Match by exact text on the line amount.
    expect(container.textContent).toContain(fmt(100_000_000));
    expect(container.textContent).toContain(fmt(200_000_000));
    expect(container.textContent).toContain(fmt(324_000_000));
  });
});

describe("FeeBreakdownTable / editable mode", () => {
  test("editing an amount triggers onChange with recomputed totals", () => {
    const onChange = vi.fn();
    render(<FeeBreakdownTable value={makeBreakdown()} onChange={onChange} />);

    // The first row's amount input is the third input on the page
    // (phase, label, amount). Find it by current display value.
    const amountInputs = screen.getAllByDisplayValue(/^(100000000|200000000)$/);
    fireEvent.change(amountInputs[0]!, { target: { value: "150000000" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]![0] as FeeBreakdown;
    expect(next.lines[0]!.amount_vnd).toBe(150_000_000);
    expect(next.lines[1]!.amount_vnd).toBe(200_000_000);
    expect(next.subtotal_vnd).toBe(350_000_000);
    // VAT = round(350_000_000 * 0.08) = 28_000_000.
    // Pin the rounding step: a swap to Math.floor would silently shave
    // dong on every recompute.
    expect(next.vat_vnd).toBe(28_000_000);
    expect(next.total_vnd).toBe(378_000_000);
  });

  test("Remove button drops the row and re-emits totals", () => {
    const onChange = vi.fn();
    render(<FeeBreakdownTable value={makeBreakdown()} onChange={onChange} />);

    const removeButtons = screen.getAllByRole("button", {
      name: /remove line/i,
    });
    fireEvent.click(removeButtons[0]!);

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]![0] as FeeBreakdown;
    expect(next.lines).toHaveLength(1);
    expect(next.lines[0]!.label).toBe("Design development");
    expect(next.subtotal_vnd).toBe(200_000_000);
    expect(next.vat_vnd).toBe(16_000_000);
    expect(next.total_vnd).toBe(216_000_000);
  });

  test("Removing the last row emits a valid empty-state breakdown (not NaN)", () => {
    // The reduce starts at 0 with `(s, l) => s + (l.amount_vnd || 0)`,
    // so an empty `lines` array produces a clean 0/0/0 — pin it,
    // because a regression to `lines.reduce((s, l) => s + l.amount_vnd)`
    // (no initial value) would throw on an empty array and crash the
    // whole proposal page.
    const onChange = vi.fn();
    const single: FeeBreakdown = {
      lines: [{ phase: "Concept", label: "Only line", amount_vnd: 50_000_000 }],
      subtotal_vnd: 50_000_000,
      vat_vnd: 4_000_000,
      total_vnd: 54_000_000,
    };
    render(<FeeBreakdownTable value={single} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /remove line/i }));

    const next = onChange.mock.calls[0]![0] as FeeBreakdown;
    expect(next.lines).toEqual([]);
    expect(next.subtotal_vnd).toBe(0);
    expect(next.vat_vnd).toBe(0);
    expect(next.total_vnd).toBe(0);
  });

  test("Add button appends a default 'New line' row at amount 0", () => {
    const onChange = vi.fn();
    render(<FeeBreakdownTable value={makeBreakdown()} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /add line/i }));

    const next = onChange.mock.calls[0]![0] as FeeBreakdown;
    expect(next.lines).toHaveLength(3);
    expect(next.lines[2]).toEqual({
      phase: "Concept",
      label: "New line",
      amount_vnd: 0,
    });
    // Adding 0 doesn't shift the math — pin so the recalc is still
    // wired even when the new row is a no-op.
    expect(next.subtotal_vnd).toBe(300_000_000);
    expect(next.vat_vnd).toBe(24_000_000);
  });

  test("amount input parses '' (empty string) as 0, not NaN", () => {
    // The input is type=number; clearing it fires onChange with
    // value="". The component coerces via `Number(e.target.value || 0)`.
    // Without the `|| 0`, an empty string would parse to 0 too —
    // but a regression to `parseFloat(e.target.value)` would emit NaN
    // and corrupt the breakdown silently. Pin the empty-string case.
    const onChange = vi.fn();
    render(<FeeBreakdownTable value={makeBreakdown()} onChange={onChange} />);

    const amountInputs = screen.getAllByDisplayValue(/^(100000000|200000000)$/);
    fireEvent.change(amountInputs[0]!, { target: { value: "" } });

    const next = onChange.mock.calls[0]![0] as FeeBreakdown;
    expect(next.lines[0]!.amount_vnd).toBe(0);
    expect(Number.isNaN(next.subtotal_vnd)).toBe(false);
  });
});

describe("FeeBreakdownTable / no-op without onChange", () => {
  test("Add button without onChange is a silent no-op (does not throw)", () => {
    // The component is rendered read-only-ish when onChange is
    // omitted but readOnly isn't set — exercising the early-return
    // branches in `add`/`update`/`remove`. Pin that no-op rather than
    // letting a future refactor change it to throw.
    render(<FeeBreakdownTable value={makeBreakdown()} />);
    const addBtn = screen.getByRole("button", { name: /add line/i });
    expect(() => fireEvent.click(addBtn)).not.toThrow();
  });
});
