"use client";

import { useState } from "react";

import { Input } from "@aec/ui/primitives";
import { useSuppliers } from "@/hooks/costpulse";

export default function SupplierDirectoryPage(): JSX.Element {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | undefined>();
  const [verifiedOnly, setVerifiedOnly] = useState(false);

  const { data, isLoading } = useSuppliers({
    q: q || undefined,
    category,
    verified_only: verifiedOnly,
  });

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <h1 className="text-2xl font-bold text-slate-900">Suppliers</h1>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search suppliers…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-sm"
        />
        <select
          className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm"
          value={category ?? ""}
          onChange={(e) => setCategory(e.target.value || undefined)}
        >
          <option value="">All categories</option>
          <option>concrete</option>
          <option>steel</option>
          <option>finishing</option>
          <option>mep</option>
          <option>timber</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={verifiedOnly}
            onChange={(e) => setVerifiedOnly(e.target.checked)}
          />
          Verified only
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {isLoading && <div className="text-slate-500">Loading…</div>}
        {(data?.items ?? []).map((s) => (
          <div key={s.id} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="font-semibold text-slate-900">{s.name}</div>
              {s.verified && (
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                  Verified
                </span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1 text-xs">
              {s.categories.map((c) => (
                <span key={c} className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
                  {c}
                </span>
              ))}
            </div>
            <div className="mt-2 text-xs text-slate-500">
              {s.provinces.length > 0 ? s.provinces.join(", ") : "Nationwide"}
            </div>
            {s.rating && <div className="mt-2 text-sm">★ {Number(s.rating).toFixed(1)}</div>}
          </div>
        ))}
        {!isLoading && (data?.items.length ?? 0) === 0 && (
          <div className="col-span-full rounded-lg border border-dashed border-slate-300 p-6 text-center text-slate-500">
            No suppliers match your filters.
          </div>
        )}
      </div>
    </div>
  );
}
