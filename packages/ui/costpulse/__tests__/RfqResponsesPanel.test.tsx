import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { Rfq, Supplier } from "@aec/types";

import { RfqResponsesPanel } from "../RfqResponsesPanel";

/**
 * Pin the row-ordering invariant — buyers triage by status, so:
 *   1. responded (actionable)
 *   2. dispatched (waiting on supplier)
 *   3. bounced / skipped (something went wrong)
 *   4. pending (supplier was added to sent_to but not yet emailed)
 *
 * If a refactor inverts this order, the buyer's eye lands on the
 * least-actionable row first. Test-as-spec.
 */

function makeSupplier(id: string, overrides: Partial<Supplier> = {}): Supplier {
  return {
    id,
    organization_id: "org-1",
    name: `Supplier ${id.slice(-1)}`,
    categories: [],
    provinces: [],
    contact: {},
    verified: true,
    rating: null,
    created_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

function makeRfq(overrides: Partial<Rfq> = {}): Rfq {
  return {
    id: "rfq-1",
    project_id: null,
    estimate_id: null,
    status: "responded",
    sent_to: [],
    responses: [],
    deadline: null,
    accepted_supplier_id: null,
    accepted_at: null,
    created_at: "2026-04-25T10:00:00Z",
    ...overrides,
  };
}


describe("<RfqResponsesPanel>", () => {
  test("orders rows responded > dispatched > bounced > pending", () => {
    const a = "00000000-0000-0000-0000-00000000000a";  // pending
    const b = "00000000-0000-0000-0000-00000000000b";  // dispatched
    const c = "00000000-0000-0000-0000-00000000000c";  // responded
    const d = "00000000-0000-0000-0000-00000000000d";  // bounced

    const rfq = makeRfq({
      sent_to: [a, b, c, d],
      responses: [
        { supplier_id: b, status: "dispatched", quote: null },
        {
          supplier_id: c,
          status: "responded",
          quote: {
            total_vnd: "1000000",
            lead_time_days: 7,
            valid_until: null,
            notes: null,
            line_items: [],
          },
        },
        { supplier_id: d, status: "bounced", quote: null },
        // a has NO entry — should show as pending
      ],
    });
    const suppliers = [
      makeSupplier(a, { name: "Pending Co" }),
      makeSupplier(b, { name: "Dispatched Co" }),
      makeSupplier(c, { name: "Responded Co" }),
      makeSupplier(d, { name: "Bounced Co" }),
    ];

    render(<RfqResponsesPanel rfq={rfq} suppliers={suppliers} />);

    const rows = screen.getAllByRole("row").slice(1);  // strip header
    const names = rows.map((r) => r.textContent ?? "");
    const idxResponded = names.findIndex((t) => t.includes("Responded Co"));
    const idxDispatched = names.findIndex((t) => t.includes("Dispatched Co"));
    const idxBounced = names.findIndex((t) => t.includes("Bounced Co"));
    const idxPending = names.findIndex((t) => t.includes("Pending Co"));

    expect(idxResponded).toBeLessThan(idxDispatched);
    expect(idxDispatched).toBeLessThan(idxBounced);
    expect(idxBounced).toBeLessThan(idxPending);
  });

  test("shows pending row for suppliers on sent_to but missing from responses", () => {
    const a = "00000000-0000-0000-0000-00000000000a";
    const rfq = makeRfq({ sent_to: [a], responses: [] });
    const suppliers = [makeSupplier(a, { name: "Acme" })];

    render(<RfqResponsesPanel rfq={rfq} suppliers={suppliers} />);

    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText(/pending/i)).toBeInTheDocument();
  });

  test("renders empty state when sent_to is empty", () => {
    render(<RfqResponsesPanel rfq={makeRfq({ sent_to: [] })} suppliers={[]} />);
    expect(screen.getByText(/No suppliers/i)).toBeInTheDocument();
  });

  test("renders quote total when supplier responded with a quote", () => {
    const a = "00000000-0000-0000-0000-00000000000a";
    const rfq = makeRfq({
      sent_to: [a],
      responses: [
        {
          supplier_id: a,
          status: "responded",
          quote: {
            total_vnd: "12500000",
            lead_time_days: 14,
            valid_until: null,
            notes: null,
            line_items: [],
          },
        },
      ],
    });
    const suppliers = [makeSupplier(a)];

    render(<RfqResponsesPanel rfq={rfq} suppliers={suppliers} />);

    // Total + lead time both surface in the row.
    expect(screen.getByText(/12.500.000|12,500,000/)).toBeInTheDocument();
    expect(screen.getByText(/14/)).toBeInTheDocument();
  });
});
