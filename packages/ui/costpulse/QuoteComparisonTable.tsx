"use client";

import { useMemo } from "react";
import type { Rfq, RfqResponseEntry, Supplier } from "@aec/types";

import { formatVnd } from "./formatters";

interface QuoteComparisonTableProps {
  rfq: Rfq;
  /**
   * Supplier directory used to resolve `supplier_id` → display name.
   * Same list the `RfqResponsesPanel` already consumes — pass it
   * through rather than re-fetching.
   */
  suppliers: Supplier[];
  /**
   * Optional accept callback. When provided, each responding-supplier
   * column gets a "Pick" button in the footer that calls
   * `onAcceptWinner(supplierId)`. The component doesn't perform the
   * mutation itself — keeps the UI package framework-agnostic and lets
   * the consumer wire it to react-query / their navigation. Omit this
   * prop on read-only views (audit log, archived RFQs).
   */
  onAcceptWinner?: (winnerSupplierId: string) => void;
  /** Disables every Pick button while a mutation is in flight. */
  acceptingSupplierId?: string | null;
  className?: string;
}

interface QuoteCol {
  supplierId: string;
  supplierName: string;
  totalVnd: bigint | null;
  leadTimeDays: number | null;
  /** material_code → unit_price_vnd (bigint, or null when not quoted). */
  pricesByCode: Map<string, bigint>;
  /**
   * Free-form lines this supplier quoted that don't carry a
   * `material_code`. Surfaced under the table so they aren't lost.
   */
  unmappedLines: Array<{ description: string; unit_price_vnd: bigint | null }>;
}

interface QuoteRow {
  /** Stable identifier — material_code preferred, falls back to description. */
  key: string;
  description: string;
  materialCode: string | null;
  unit: string | null;
  /** Buyer's quantity for this line (undefined = supplier-only line). */
  quantity: number | null;
}

/**
 * Per-BOQ-line cost comparison across suppliers who responded.
 *
 * The vertical axis is the buyer's BOQ digest (anchored on the union
 * of every supplier's `material_code` quotes — even lines the buyer
 * didn't explicitly send, in case a supplier added context). The
 * horizontal axis is one column per responding supplier.
 *
 * Per-row highlighting:
 *   • Lowest unit price for the row gets a green badge.
 *   • A supplier whose quote is >50% above the row median gets an
 *     amber tint (likely overpriced or quoting a different material).
 *
 * Bottom rows summarise: each supplier's total quote + lead time +
 * "won X / Y rows" (rows where they were lowest).
 *
 * Fallbacks:
 *   • Supplier hasn't responded → column rendered with "—" cells +
 *     a "(pending)" subhead so the buyer sees who's missing.
 *   • Supplier quoted only a top-line `total_vnd` (no line items) →
 *     row cells show "—" but the totals row shows their total. This
 *     handles the common "I'll quote ₫150M flat for the package" case.
 */
export function QuoteComparisonTable({
  rfq,
  suppliers,
  onAcceptWinner,
  acceptingSupplierId = null,
  className = "",
}: QuoteComparisonTableProps): JSX.Element {
  const cols = useMemo(() => buildCols(rfq, suppliers), [rfq, suppliers]);
  const rows = useMemo(() => buildRows(cols), [cols]);

  if (cols.length === 0) {
    return (
      <div className={`rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 ${className}`}>
        No suppliers attached to this RFQ.
      </div>
    );
  }

  // Suppliers we have at least one quote from (for the win-rate footer).
  const respondingCols = cols.filter((c) => c.totalVnd != null || c.pricesByCode.size > 0);
  const wins = computeWins(rows, respondingCols);

  return (
    <div className={`overflow-hidden rounded-lg border border-slate-200 bg-white ${className}`}>
      <header className="border-b border-slate-100 px-4 py-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          Quote comparison
        </h3>
        <p className="text-xs text-slate-500">
          {respondingCols.length} of {cols.length} suppliers have responded.
          {rows.length > 0 ? ` ${rows.length} priced line(s).` : ""}
        </p>
      </header>

      {rows.length === 0 ? (
        <div className="px-4 py-6 text-sm text-slate-500">
          No line-item prices submitted yet — only top-line totals (see footer).
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="sticky left-0 bg-slate-50 px-3 py-2">Item</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2">Unit</th>
                {cols.map((col) => (
                  <th key={col.supplierId} className="px-3 py-2 text-right">
                    <div className="font-medium text-slate-900">{col.supplierName}</div>
                    {col.totalVnd == null && col.pricesByCode.size === 0 ? (
                      <div className="text-[10px] font-normal text-slate-500">(pending)</div>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <ComparisonRow key={row.key} row={row} cols={cols} />
              ))}
            </tbody>
            <tfoot className="bg-slate-50 text-xs">
              <tr className="border-t-2 border-slate-200">
                <td className="sticky left-0 bg-slate-50 px-3 py-2 font-semibold uppercase tracking-wide text-slate-700">
                  Total
                </td>
                <td colSpan={2} />
                {cols.map((col) => (
                  <td key={col.supplierId} className="px-3 py-2 text-right font-semibold">
                    {col.totalVnd != null ? formatVnd(col.totalVnd.toString()) : "—"}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-50 px-3 py-2 text-slate-600">
                  Lead time
                </td>
                <td colSpan={2} />
                {cols.map((col) => (
                  <td key={col.supplierId} className="px-3 py-2 text-right text-slate-700">
                    {col.leadTimeDays != null ? `${col.leadTimeDays}d` : "—"}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-50 px-3 py-2 text-slate-600">
                  Lowest on
                </td>
                <td colSpan={2} />
                {cols.map((col) => (
                  <td key={col.supplierId} className="px-3 py-2 text-right text-slate-700">
                    {wins.get(col.supplierId) ?? 0} / {rows.length}
                  </td>
                ))}
              </tr>
              {/* Pick row — present only when:
                    1. The consumer wired an accept handler, AND
                    2. The RFQ isn't already closed (no point picking
                       again, and the API would 409 anyway).
                  Each cell is a Pick button for that supplier; pending
                  / non-responding columns get a disabled placeholder
                  so the row stays aligned. The already-accepted
                  supplier (if any) renders a "✓ Accepted" badge
                  instead of a button. */}
              {onAcceptWinner && rfq.status !== "closed" ? (
                <tr className="border-t border-slate-200 bg-white">
                  <td className="sticky left-0 bg-white px-3 py-2 font-semibold uppercase tracking-wide text-slate-700">
                    Pick
                  </td>
                  <td colSpan={2} />
                  {cols.map((col) => (
                    <td key={col.supplierId} className="px-3 py-2 text-right">
                      <PickButton
                        col={col}
                        rfq={rfq}
                        accepting={acceptingSupplierId === col.supplierId}
                        disabled={acceptingSupplierId !== null}
                        onPick={() => onAcceptWinner(col.supplierId)}
                      />
                    </td>
                  ))}
                </tr>
              ) : null}
            </tfoot>
          </table>
        </div>
      )}

      {/* Lines that didn't have a material_code don't slot into the
          comparison grid; render them flat below so the supplier's
          extra context isn't dropped silently. */}
      {cols.some((c) => c.unmappedLines.length > 0) ? (
        <UnmappedLines cols={cols} />
      ) : null}
    </div>
  );
}


// ---------- Comparison row (per BOQ line) ----------


function ComparisonRow({ row, cols }: { row: QuoteRow; cols: QuoteCol[] }): JSX.Element {
  // Compute lowest + median across responding suppliers for this row.
  // BigInt math — VND prices can exceed Number.MAX_SAFE_INTEGER on
  // large estimates (10-digit totals × thousands of suppliers).
  const prices: bigint[] = [];
  for (const col of cols) {
    const p = col.pricesByCode.get(row.key);
    if (p != null) prices.push(p);
  }
  prices.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  // Index-access type-narrowed: noUncheckedIndexedAccess infers
  // `prices[0]` as `bigint | undefined`; coalesce explicitly.
  const lowest: bigint | null = prices[0] ?? null;
  const median: bigint | null =
    prices.length > 0 ? (prices[Math.floor(prices.length / 2)] ?? null) : null;

  return (
    <tr className="border-t border-slate-100">
      <td className="sticky left-0 bg-white px-3 py-2">
        <div className="font-medium text-slate-900">{row.description}</div>
        {row.materialCode ? (
          <div className="font-mono text-xs text-slate-500">{row.materialCode}</div>
        ) : null}
      </td>
      <td className="px-3 py-2 text-right">{row.quantity ?? "—"}</td>
      <td className="px-3 py-2 text-slate-700">{row.unit ?? "—"}</td>
      {cols.map((col) => {
        const p = col.pricesByCode.get(row.key) ?? null;
        return (
          <td key={col.supplierId} className="px-3 py-2 text-right tabular-nums">
            <PriceCell price={p} lowest={lowest} median={median} />
          </td>
        );
      })}
    </tr>
  );
}


function PickButton({
  col,
  rfq,
  accepting,
  disabled,
  onPick,
}: {
  col: QuoteCol;
  rfq: Rfq;
  accepting: boolean;
  disabled: boolean;
  onPick: () => void;
}): JSX.Element {
  // The "already accepted" branch — the buyer picked this supplier
  // before. We still render the row when `rfq.status !== "closed"`
  // (e.g. the buyer's mid-flight on a re-open flow) but show the
  // current-winner badge instead of a button so the visual state is
  // unambiguous.
  const isAccepted = rfq.accepted_supplier_id === col.supplierId;
  if (isAccepted) {
    return (
      <span className="inline-block rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
        ✓ Accepted
      </span>
    );
  }
  // No quote → can't pick. Render a placeholder so the column doesn't
  // collapse but the button is unmistakably absent.
  const hasQuote = col.totalVnd != null || col.pricesByCode.size > 0;
  if (!hasQuote) {
    return <span className="text-xs text-slate-400">—</span>;
  }
  return (
    <button
      type="button"
      onClick={onPick}
      disabled={disabled}
      className="rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {accepting ? "Picking…" : "Pick"}
    </button>
  );
}


function PriceCell({
  price,
  lowest,
  median,
}: {
  price: bigint | null;
  lowest: bigint | null;
  median: bigint | null;
}): JSX.Element {
  if (price == null) return <span className="text-slate-400">—</span>;
  const isLowest = lowest != null && price === lowest;
  // 50% above median → flag as outlier. Use BigInt math: `price > median * 3n / 2n`.
  const isOutlier = median != null && median > 0n && price * 2n > median * 3n;

  const className = isLowest
    ? "rounded bg-green-50 px-1.5 py-0.5 font-semibold text-green-800"
    : isOutlier
      ? "rounded bg-amber-50 px-1.5 py-0.5 text-amber-800"
      : "text-slate-900";

  return <span className={className}>{formatVnd(price.toString())}</span>;
}


function UnmappedLines({ cols }: { cols: QuoteCol[] }): JSX.Element {
  return (
    <section className="border-t border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
      <p className="font-semibold uppercase tracking-wide">Unmapped supplier lines</p>
      <p className="mt-0.5 text-slate-500">
        Lines a supplier added without a `material_code` — they don't slot
        into the BOQ grid above but are preserved here for the buyer to see.
      </p>
      <ul className="mt-2 space-y-1">
        {cols.flatMap((col) =>
          col.unmappedLines.map((line, idx) => (
            <li key={`${col.supplierId}-${idx}`} className="flex justify-between gap-4">
              <span>
                <span className="font-medium text-slate-700">{col.supplierName}:</span>{" "}
                {line.description}
              </span>
              <span className="tabular-nums text-slate-700">
                {line.unit_price_vnd != null ? formatVnd(line.unit_price_vnd.toString()) : "—"}
              </span>
            </li>
          )),
        )}
      </ul>
    </section>
  );
}


// ---------- Pure transforms (testable in isolation) ----------


/**
 * Build one column per supplier on `rfq.sent_to`. A supplier without a
 * response slot still gets a column (rendered as "(pending)") — the
 * buyer's mental model is "everyone I sent it to", not "everyone who
 * replied".
 *
 * Exported for unit tests; the component itself doesn't expose it.
 */
export function buildCols(rfq: Rfq, suppliers: Supplier[]): QuoteCol[] {
  const supplierById = new Map(suppliers.map((s) => [s.id, s]));
  const responseBySupplier = new Map<string, RfqResponseEntry>();
  for (const entry of rfq.responses ?? []) {
    if (entry?.supplier_id) {
      responseBySupplier.set(String(entry.supplier_id), entry);
    }
  }

  return (rfq.sent_to ?? []).map((sid) => {
    const supplier = supplierById.get(sid);
    const entry = responseBySupplier.get(sid);
    const quote = entry?.quote ?? null;

    const pricesByCode = new Map<string, bigint>();
    const unmappedLines: QuoteCol["unmappedLines"] = [];
    if (quote?.line_items) {
      for (const line of quote.line_items) {
        const price = parseBigInt(line.unit_price_vnd);
        if (line.material_code) {
          if (price != null) pricesByCode.set(line.material_code, price);
        } else {
          unmappedLines.push({
            description: line.description,
            unit_price_vnd: price,
          });
        }
      }
    }

    return {
      supplierId: sid,
      supplierName: supplier?.name ?? "(supplier removed)",
      totalVnd: parseBigInt(quote?.total_vnd ?? null),
      leadTimeDays: quote?.lead_time_days ?? null,
      pricesByCode,
      unmappedLines,
    };
  });
}


/**
 * Union of every material_code across all responding suppliers.
 *
 * We anchor on the supplier responses rather than the buyer's BOQ
 * because (a) we don't have the BOQ in this component (it lives on
 * the estimate), and (b) suppliers occasionally quote substitutions
 * (offer "CONC_C35" when buyer asked for "CONC_C30") — those should
 * appear in the comparison so the buyer can spot them.
 */
function buildRows(cols: QuoteCol[]): QuoteRow[] {
  const seen = new Set<string>();
  const rows: QuoteRow[] = [];
  for (const col of cols) {
    for (const code of col.pricesByCode.keys()) {
      if (seen.has(code)) continue;
      seen.add(code);
      rows.push({
        key: code,
        description: code,  // We don't have a description here without the BOQ; code is acceptable.
        materialCode: code,
        unit: null,
        quantity: null,
      });
    }
  }
  return rows;
}


function computeWins(rows: QuoteRow[], respondingCols: QuoteCol[]): Map<string, number> {
  const wins = new Map<string, number>();
  for (const col of respondingCols) wins.set(col.supplierId, 0);
  for (const row of rows) {
    let lowest: bigint | null = null;
    let lowestSid: string | null = null;
    for (const col of respondingCols) {
      const p = col.pricesByCode.get(row.key);
      if (p == null) continue;
      if (lowest == null || p < lowest) {
        lowest = p;
        lowestSid = col.supplierId;
      }
    }
    if (lowestSid != null) {
      wins.set(lowestSid, (wins.get(lowestSid) ?? 0) + 1);
    }
  }
  return wins;
}


function parseBigInt(s: string | null | undefined): bigint | null {
  if (s == null || s === "") return null;
  // VND quotes are integer-valued (no fractional dong). Trim a `.0` /
  // `.00` tail rather than rejecting — Pydantic occasionally emits
  // Decimal as "123.0".
  const trimmed = String(s).trim().replace(/\.0+$/, "");
  // BigInt("12500.5") throws; reject anything not pure digits + sign.
  if (!/^-?\d+$/.test(trimmed)) return null;
  try {
    return BigInt(trimmed);
  } catch {
    return null;
  }
}
