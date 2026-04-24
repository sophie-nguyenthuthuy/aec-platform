"use client";
import { useMemo } from "react";
import { Trash2 } from "lucide-react";
import type { FeeBreakdown, FeeLine } from "@aec/types/winwork";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";

interface FeeBreakdownTableProps {
  value: FeeBreakdown;
  onChange?: (next: FeeBreakdown) => void;
  readOnly?: boolean;
}

function fmt(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n);
}

function recalc(lines: FeeLine[], vatPct = 0.08): FeeBreakdown {
  const subtotal = lines.reduce((s, l) => s + (l.amount_vnd || 0), 0);
  const vat = Math.round(subtotal * vatPct);
  return { lines, subtotal_vnd: subtotal, vat_vnd: vat, total_vnd: subtotal + vat };
}

export function FeeBreakdownTable({ value, onChange, readOnly }: FeeBreakdownTableProps) {
  const rows = useMemo(() => value.lines, [value.lines]);

  function update(idx: number, patch: Partial<FeeLine>) {
    if (!onChange) return;
    const next = rows.map((row, i) => (i === idx ? { ...row, ...patch } : row));
    onChange(recalc(next));
  }

  function remove(idx: number) {
    if (!onChange) return;
    onChange(recalc(rows.filter((_, i) => i !== idx)));
  }

  function add() {
    if (!onChange) return;
    onChange(recalc([...rows, { phase: "Concept", label: "New line", amount_vnd: 0 }]));
  }

  return (
    <div className="space-y-3">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase text-muted-foreground">
            <th className="py-2">Phase</th>
            <th>Label</th>
            <th className="text-right">Amount (VND)</th>
            {!readOnly && <th className="w-8" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((line, idx) => (
            <tr key={`${line.phase}-${idx}`} className="border-b last:border-0">
              <td className="py-2 pr-3 align-top">
                {readOnly ? (
                  line.phase
                ) : (
                  <Input value={line.phase} onChange={(e) => update(idx, { phase: e.target.value })} />
                )}
              </td>
              <td className="pr-3 align-top">
                {readOnly ? (
                  line.label
                ) : (
                  <Input value={line.label} onChange={(e) => update(idx, { label: e.target.value })} />
                )}
              </td>
              <td className="pr-3 text-right align-top">
                {readOnly ? (
                  fmt(line.amount_vnd)
                ) : (
                  <Input
                    type="number"
                    inputMode="numeric"
                    className="text-right"
                    value={line.amount_vnd}
                    onChange={(e) => update(idx, { amount_vnd: Number(e.target.value || 0) })}
                  />
                )}
              </td>
              {!readOnly && (
                <td className="align-top">
                  <Button variant="ghost" size="icon" onClick={() => remove(idx)} aria-label="Remove line">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="text-sm">
            <td colSpan={2} className="py-2 pr-3 text-right text-muted-foreground">Subtotal</td>
            <td className="text-right font-medium">{fmt(value.subtotal_vnd)}</td>
            {!readOnly && <td />}
          </tr>
          <tr className="text-sm">
            <td colSpan={2} className="py-1 pr-3 text-right text-muted-foreground">VAT (8%)</td>
            <td className="text-right">{fmt(value.vat_vnd)}</td>
            {!readOnly && <td />}
          </tr>
          <tr className="border-t text-base">
            <td colSpan={2} className="py-2 pr-3 text-right font-semibold">Total</td>
            <td className="text-right font-semibold">{fmt(value.total_vnd)}</td>
            {!readOnly && <td />}
          </tr>
        </tfoot>
      </table>
      {!readOnly && (
        <Button variant="outline" size="sm" onClick={add}>
          Add line
        </Button>
      )}
    </div>
  );
}
