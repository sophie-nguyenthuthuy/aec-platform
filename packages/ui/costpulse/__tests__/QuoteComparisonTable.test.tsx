import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { Rfq, Supplier } from "@aec/types";

import { QuoteComparisonTable } from "../QuoteComparisonTable";

/**
 * Pin the buyer-decision UX:
 *
 *   1. The "Pick" row only renders when (a) the parent passed an
 *      `onAcceptWinner`, AND (b) the RFQ isn't already closed.
 *   2. A supplier with no quote shows a placeholder, NOT a clickable
 *      Pick button — clicking would 409.
 *   3. The currently-accepted supplier shows a "✓ Accepted" badge
 *      instead of a Pick button.
 *   4. The `acceptingSupplierId` prop disables every other Pick
 *      button in the row so the buyer can't fire two accepts in a
 *      race.
 */

function makeSupplier(id: string, name: string): Supplier {
  return {
    id,
    organization_id: "org-1",
    name,
    categories: [],
    provinces: [],
    contact: {},
    verified: true,
    rating: null,
    created_at: "2026-04-01T00:00:00Z",
  };
}

function makeQuote(total: string) {
  return {
    total_vnd: total,
    lead_time_days: 14,
    valid_until: null,
    notes: null,
    line_items: [
      {
        material_code: "CONC_C30",
        description: "Concrete C30",
        quantity: 100,
        unit: "m3",
        unit_price_vnd: "2000000",
      },
    ],
  };
}

function makeRfq(suppliers: string[], quotes: Record<string, ReturnType<typeof makeQuote>>): Rfq {
  return {
    id: "rfq-1",
    project_id: null,
    estimate_id: null,
    status: "responded",
    sent_to: suppliers,
    responses: suppliers.map((id) => ({
      supplier_id: id,
      status: quotes[id] ? "responded" : "dispatched",
      quote: quotes[id] ?? null,
    })),
    deadline: null,
    accepted_supplier_id: null,
    accepted_at: null,
    created_at: "2026-04-25T10:00:00Z",
  };
}


describe("<QuoteComparisonTable> — Pick winner UX", () => {
  test("renders no Pick row when onAcceptWinner is not provided", () => {
    const a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const rfq = makeRfq([a], { [a]: makeQuote("1000000") });
    render(<QuoteComparisonTable rfq={rfq} suppliers={[makeSupplier(a, "A Co")]} />);

    // The "Pick" row label appears only when the action is wired.
    expect(screen.queryByText(/^Pick$/)).not.toBeInTheDocument();
  });

  test("renders Pick row when onAcceptWinner is provided AND RFQ not closed", () => {
    const a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const rfq = makeRfq([a], { [a]: makeQuote("1000000") });
    render(
      <QuoteComparisonTable
        rfq={rfq}
        suppliers={[makeSupplier(a, "A Co")]}
        onAcceptWinner={vi.fn()}
      />,
    );

    // The "Pick" label appears as both a row header (<td>) and the
    // button (<button>). Both must exist when the row is rendered.
    expect(screen.getAllByText("Pick").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Pick" })).toBeInTheDocument();
  });

  test("hides Pick row when RFQ is already closed", () => {
    const a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const rfq: Rfq = {
      ...makeRfq([a], { [a]: makeQuote("1000000") }),
      status: "closed",
    };
    render(
      <QuoteComparisonTable
        rfq={rfq}
        suppliers={[makeSupplier(a, "A Co")]}
        onAcceptWinner={vi.fn()}
      />,
    );

    expect(screen.queryByText(/^Pick$/)).not.toBeInTheDocument();
  });

  test("shows ✓ Accepted badge on the previously-accepted supplier's column", () => {
    const winner = "11111111-1111-1111-1111-111111111111";
    const loser = "22222222-2222-2222-2222-222222222222";
    const rfq: Rfq = {
      ...makeRfq([winner, loser], {
        [winner]: makeQuote("1000000"),
        [loser]: makeQuote("1500000"),
      }),
      // Buyer already picked the winner; status is still "responded"
      // (e.g. if buyer is mid-flight on an undo flow).
      accepted_supplier_id: winner,
      accepted_at: "2026-04-29T10:00:00Z",
    };

    render(
      <QuoteComparisonTable
        rfq={rfq}
        suppliers={[makeSupplier(winner, "Winner"), makeSupplier(loser, "Loser")]}
        onAcceptWinner={vi.fn()}
      />,
    );

    // Winner shows the badge, not a Pick button.
    expect(screen.getByText(/✓ Accepted/i)).toBeInTheDocument();
    const pickButtons = screen.getAllByRole("button", { name: "Pick" });
    expect(pickButtons).toHaveLength(1);
  });

  test("calls onAcceptWinner with supplier id when Pick clicked", () => {
    const a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const rfq = makeRfq([a], { [a]: makeQuote("1000000") });
    const onAccept = vi.fn();
    render(
      <QuoteComparisonTable
        rfq={rfq}
        suppliers={[makeSupplier(a, "A Co")]}
        onAcceptWinner={onAccept}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Pick" }));
    expect(onAccept).toHaveBeenCalledWith(a);
  });

  test("shows 'Picking…' on the supplier whose accept is in flight", () => {
    const a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
    const rfq = makeRfq([a, b], { [a]: makeQuote("1000000"), [b]: makeQuote("2000000") });

    render(
      <QuoteComparisonTable
        rfq={rfq}
        suppliers={[makeSupplier(a, "A"), makeSupplier(b, "B")]}
        onAcceptWinner={vi.fn()}
        acceptingSupplierId={a}
      />,
    );

    // The accepting supplier's button shows "Picking…"; both buttons
    // disabled (so the buyer can't flip-flop mid-flight).
    expect(screen.getByRole("button", { name: "Picking…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pick" })).toBeDisabled();
  });

  test("renders placeholder instead of Pick button for suppliers with no quote", () => {
    const a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";  // dispatched, no quote
    const rfq = makeRfq([a], {});  // no quotes at all
    render(
      <QuoteComparisonTable
        rfq={rfq}
        suppliers={[makeSupplier(a, "A")]}
        onAcceptWinner={vi.fn()}
      />,
    );

    // No clickable Pick button for a non-responding supplier.
    expect(screen.queryByRole("button", { name: "Pick" })).not.toBeInTheDocument();
  });
});
