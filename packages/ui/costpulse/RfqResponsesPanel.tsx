"use client";

import { useMemo } from "react";
import type { Rfq, RfqResponseEntry, Supplier } from "@aec/types";

import { formatVnd } from "./formatters";

interface RfqResponsesPanelProps {
  rfq: Rfq;
  /**
   * Supplier directory used to resolve `supplier_id` → display name +
   * contact email. Pass the same suppliers list you've already loaded
   * for the RFQ Manager — re-fetching here would be wasteful and would
   * slow down the panel-open animation.
   */
  suppliers: Supplier[];
  className?: string;
}

interface Row {
  supplierId: string;
  supplierName: string;
  supplierEmail: string | null;
  entry: RfqResponseEntry | null;
  /** True when supplier_id is on `sent_to` but has no entry in `responses` yet. */
  missingEntry: boolean;
}

/**
 * Per-supplier table of dispatch + quote state for one RFQ.
 *
 * The buyer-facing summary panel that pairs with the public supplier
 * portal: every supplier on `rfq.sent_to` gets a row here, sorted with
 * "responded" first (so the buyer sees actionable rows on top), then
 * "dispatched", then bounced/skipped. Quote totals + lead time are
 * inline so the buyer can compare at a glance without clicking through.
 *
 * Empty `responses` (e.g. dispatch hadn't run yet, or a supplier was
 * added to `sent_to` after the email blast) renders as `pending` so
 * we show *every* supplier, not just those the dispatcher has touched.
 */
export function RfqResponsesPanel({
  rfq,
  suppliers,
  className = "",
}: RfqResponsesPanelProps): JSX.Element {
  const rows = useMemo(() => buildRows(rfq, suppliers), [rfq, suppliers]);
  const responded = rows.filter((r) => r.entry?.status === "responded").length;

  if (rows.length === 0) {
    // Defensive: an RFQ with no `sent_to` shouldn't exist (`RfqCreate`
    // requires `min_length=1`), but render a sane empty state just in
    // case a hand-edit lands one in the DB.
    return (
      <div className={`rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500 ${className}`}>
        No suppliers were attached to this RFQ.
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-lg border border-slate-200 bg-white ${className}`}>
      <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2 text-xs">
        <h3 className="font-semibold uppercase tracking-wide text-slate-700">
          Responses
        </h3>
        <p className="text-slate-500">
          {responded} / {rows.length} responded
        </p>
      </header>
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="px-3 py-2">Supplier</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2 text-right">Quote total</th>
            <th className="px-3 py-2 text-right">Lead time</th>
            <th className="px-3 py-2">Last update</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <ResponseRow key={row.supplierId} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}


function ResponseRow({ row }: { row: Row }): JSX.Element {
  const status = row.entry?.status ?? "pending";
  const quote = row.entry?.quote;
  const lastUpdate = row.entry?.responded_at ?? row.entry?.dispatched_at ?? null;

  const reason = !row.entry?.delivery?.delivered ? row.entry?.delivery?.reason ?? null : null;

  return (
    <tr className="border-t border-slate-100">
      <td className="px-3 py-2">
        <div className="font-medium text-slate-900">{row.supplierName}</div>
        {row.supplierEmail ? (
          <div className="text-xs text-slate-500">{row.supplierEmail}</div>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <StatusBadge status={status} reason={reason} />
      </td>
      <td className="px-3 py-2 text-right font-semibold text-slate-900">
        {quote?.total_vnd ? formatVnd(quote.total_vnd) : "—"}
      </td>
      <td className="px-3 py-2 text-right text-slate-700">
        {quote?.lead_time_days != null ? `${quote.lead_time_days}d` : "—"}
      </td>
      <td className="px-3 py-2 text-xs text-slate-500">
        {lastUpdate ? new Date(lastUpdate).toLocaleString() : "—"}
      </td>
    </tr>
  );
}


type DisplayStatus = RfqResponseEntry["status"] | "pending";

function StatusBadge({
  status,
  reason,
}: {
  status: DisplayStatus;
  reason: string | null;
}): JSX.Element {
  // Color buckets:
  //   green  = supplier action complete (responded)
  //   blue   = email out, waiting on supplier (dispatched)
  //   amber  = ops attention needed (bounced, skipped)
  //   slate  = inert (pending — dispatcher hasn't run)
  const styles: Record<DisplayStatus, string> = {
    responded: "border-green-200 bg-green-50 text-green-700",
    dispatched: "border-sky-200 bg-sky-50 text-sky-700",
    bounced: "border-amber-200 bg-amber-50 text-amber-700",
    skipped: "border-amber-200 bg-amber-50 text-amber-700",
    pending: "border-slate-200 bg-slate-50 text-slate-600",
  };
  const labels: Record<DisplayStatus, string> = {
    responded: "Responded",
    dispatched: "Dispatched",
    bounced: "Bounced",
    skipped: "Skipped",
    pending: "Pending",
  };

  return (
    <div className="flex flex-col gap-0.5">
      <span
        className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${styles[status]}`}
      >
        {labels[status]}
      </span>
      {reason ? <span className="text-xs text-amber-700">{reason}</span> : null}
    </div>
  );
}


function buildRows(rfq: Rfq, suppliers: Supplier[]): Row[] {
  const supplierById = new Map(suppliers.map((s) => [s.id, s]));
  const entryById = new Map<string, RfqResponseEntry>();
  for (const entry of rfq.responses ?? []) {
    if (entry?.supplier_id) {
      entryById.set(String(entry.supplier_id), entry);
    }
  }

  const rows: Row[] = (rfq.sent_to ?? []).map((sid) => {
    const supplier = supplierById.get(sid);
    const entry = entryById.get(sid) ?? null;
    return {
      supplierId: sid,
      // Buyer might have removed a supplier from their directory after
      // dispatch — fall back to the UUID so we still show a row.
      supplierName: supplier?.name ?? "(supplier removed)",
      supplierEmail: extractEmail(supplier),
      entry,
      missingEntry: entry === null,
    };
  });

  // Stable sort: responded → dispatched → bounced/skipped → pending.
  const order: Record<DisplayStatus, number> = {
    responded: 0,
    dispatched: 1,
    bounced: 2,
    skipped: 3,
    pending: 4,
  };
  rows.sort(
    (a, b) =>
      order[(a.entry?.status ?? "pending") as DisplayStatus] -
      order[(b.entry?.status ?? "pending") as DisplayStatus],
  );
  return rows;
}


function extractEmail(supplier: Supplier | undefined): string | null {
  if (!supplier?.contact || typeof supplier.contact !== "object") return null;
  const candidate = (supplier.contact as Record<string, unknown>).email;
  return typeof candidate === "string" ? candidate : null;
}
