"use client";

import { useState } from "react";
import type { MaterialCategory, MaterialPrice } from "@aec/types";

import { Button, Input } from "@aec/ui/primitives";
import { PriceTrendChart, formatVnd } from "@aec/ui/costpulse";
import { usePriceAlert, usePriceHistory, usePrices } from "@/hooks/costpulse";

const CATEGORIES: MaterialCategory[] = ["concrete", "steel", "finishing", "mep", "timber", "masonry"];
const PROVINCES = ["Hanoi", "HCMC", "Da Nang", "Hai Phong", "Can Tho"];

export default function PriceDatabasePage(): JSX.Element {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<MaterialCategory | undefined>();
  const [province, setProvince] = useState<string | undefined>();
  const [selected, setSelected] = useState<MaterialPrice | null>(null);

  const { data, isLoading } = usePrices({ q: q || undefined, category, province });
  const history = usePriceHistory(selected?.material_code ?? null, selected?.province ?? undefined);
  const alertMut = usePriceAlert();

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <h1 className="text-2xl font-bold text-slate-900">Price database</h1>

      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="Search by name or code…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-sm"
        />
        <select
          className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm"
          value={category ?? ""}
          onChange={(e) => setCategory((e.target.value || undefined) as MaterialCategory | undefined)}
        >
          <option value="">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <select
          className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm"
          value={province ?? ""}
          onChange={(e) => setProvince(e.target.value || undefined)}
        >
          <option value="">All provinces</option>
          {PROVINCES.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2">Material</th>
                <th className="px-3 py-2">Code</th>
                <th className="px-3 py-2">Province</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2">Effective</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-slate-500">
                    Loading…
                  </td>
                </tr>
              )}
              {(data?.items ?? []).map((p) => (
                <tr
                  key={p.id}
                  onClick={() => setSelected(p)}
                  className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${
                    selected?.id === p.id ? "bg-sky-50" : ""
                  }`}
                >
                  <td className="px-3 py-2 font-medium text-slate-900">{p.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-600">{p.material_code}</td>
                  <td className="px-3 py-2 text-slate-600">{p.province ?? "—"}</td>
                  <td className="px-3 py-2 text-right font-semibold">
                    {formatVnd(p.price_vnd)}
                    <span className="text-xs text-slate-500">/{p.unit}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-500">{p.effective_date}</td>
                </tr>
              ))}
              {!isLoading && (data?.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-slate-500">
                    No results.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="space-y-4">
          {selected ? (
            <>
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500">Selected</div>
                <div className="mt-1 text-lg font-bold text-slate-900">{selected.name}</div>
                <div className="text-sm text-slate-500">
                  {selected.material_code} · {selected.province ?? "National"}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  disabled={alertMut.isPending}
                  onClick={() =>
                    alertMut.mutate({
                      material_code: selected.material_code,
                      province: selected.province ?? undefined,
                      threshold_pct: 5,
                    })
                  }
                >
                  {alertMut.isPending
                    ? "Creating…"
                    : alertMut.isSuccess
                      ? "Alert created"
                      : "Alert me on >5% change"}
                </Button>
              </div>
              {history.data && (
                <PriceTrendChart
                  points={history.data.points}
                  pctChange30d={history.data.pct_change_30d}
                  pctChange1y={history.data.pct_change_1y}
                />
              )}
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
              Select a row to view the trend chart.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
