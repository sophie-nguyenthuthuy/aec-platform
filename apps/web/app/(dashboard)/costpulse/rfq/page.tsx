"use client";

import { useState } from "react";

import { Button } from "@aec/ui/primitives";
import { useCreateRfq, useRfqs, useSuppliers } from "@/hooks/costpulse";

export default function RfqManagerPage(): JSX.Element {
  const { data: rfqs, isLoading } = useRfqs();
  const { data: suppliers } = useSuppliers({ verified_only: true, per_page: 50 });
  const createMut = useCreateRfq();
  const [selected, setSelected] = useState<string[]>([]);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <h1 className="text-2xl font-bold text-slate-900">RFQ Manager</h1>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-lg font-semibold">New RFQ</h2>
        <div className="flex flex-wrap gap-2">
          {(suppliers?.items ?? []).map((s) => {
            const isSelected = selected.includes(s.id);
            return (
              <button
                key={s.id}
                type="button"
                onClick={() =>
                  setSelected(isSelected ? selected.filter((v) => v !== s.id) : [...selected, s.id])
                }
                className={`rounded-full border px-3 py-1 text-xs ${
                  isSelected
                    ? "border-sky-600 bg-sky-50 text-sky-700"
                    : "border-slate-200 text-slate-600 hover:bg-slate-100"
                }`}
              >
                {s.name}
              </button>
            );
          })}
        </div>
        <div className="mt-4 flex justify-end">
          <Button
            disabled={selected.length === 0 || createMut.isPending}
            onClick={async () => {
              await createMut.mutateAsync({ supplier_ids: selected });
              setSelected([]);
            }}
          >
            {createMut.isPending ? "Sending…" : `Send RFQ to ${selected.length}`}
          </Button>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">Active RFQs</h2>
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2"># Suppliers</th>
                <th className="px-3 py-2"># Responses</th>
                <th className="px-3 py-2">Deadline</th>
                <th className="px-3 py-2">Created</th>
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
              {(rfqs ?? []).map((r) => (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 capitalize">{r.status}</td>
                  <td className="px-3 py-2">{r.sent_to.length}</td>
                  <td className="px-3 py-2">{r.responses.length}</td>
                  <td className="px-3 py-2">{r.deadline ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-500">
                    {new Date(r.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
              {!isLoading && (rfqs?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-slate-500">
                    No RFQs yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
