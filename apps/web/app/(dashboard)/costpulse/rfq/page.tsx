"use client";

import { useState } from "react";

import { Button, Input } from "@aec/ui/primitives";
import { RfqResponsesPanel } from "@aec/ui/costpulse";
import { useCreateRfq, useRfqs, useSuppliers } from "@/hooks/costpulse";

export default function RfqManagerPage(): JSX.Element {
  const { data: rfqs, isLoading } = useRfqs();
  // 50 suppliers is enough for the chip-picker; if we ever blow past
  // that we'll need a search input — RFQ Manager isn't supposed to be
  // a supplier directory, just "pick the few you'll send to".
  const { data: suppliers } = useSuppliers({ verified_only: true, per_page: 50 });
  const createMut = useCreateRfq();

  const [selected, setSelected] = useState<string[]>([]);
  const [deadline, setDeadline] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filter the active-RFQ table client-side. The API doesn't yet expose
  // a status param, but the page-load list is bounded (one org, one
  // ordering) so a client filter is fine until volume justifies a query.
  const visibleRfqs = (rfqs ?? []).filter(
    (r) => !statusFilter || r.status === statusFilter,
  );

  const canSend = selected.length > 0 && !createMut.isPending;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <h1 className="text-2xl font-bold text-slate-900">RFQ Manager</h1>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-lg font-semibold">New RFQ</h2>

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-600">
          Suppliers
        </label>
        <div className="flex flex-wrap gap-2">
          {(suppliers?.items ?? []).length === 0 ? (
            <p className="text-sm text-slate-500">
              No verified suppliers yet — add some on the{" "}
              <a href="/costpulse/suppliers" className="text-sky-700 hover:underline">
                Suppliers
              </a>{" "}
              page first.
            </p>
          ) : null}
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

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="rfq-deadline"
              className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-600"
            >
              Response deadline
            </label>
            <Input
              id="rfq-deadline"
              type="date"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-4">
          <label
            htmlFor="rfq-message"
            className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-600"
          >
            Message to suppliers (optional)
          </label>
          <textarea
            id="rfq-message"
            rows={3}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Optional context — site address, project type, requested visit dates…"
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
          />
        </div>

        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-slate-500">
            {selected.length === 0
              ? "Pick one or more suppliers to enable Send."
              : `${selected.length} supplier${selected.length === 1 ? "" : "s"} selected`}
          </p>
          <Button
            disabled={!canSend}
            onClick={async () => {
              await createMut.mutateAsync({
                supplier_ids: selected,
                // Empty string from the date input means "no deadline";
                // the API expects null for that. Send the message only
                // when non-empty so we don't overwrite a per-supplier
                // template downstream with "".
                deadline: deadline || null,
                message: message.trim() || null,
              });
              setSelected([]);
              setDeadline("");
              setMessage("");
            }}
          >
            {createMut.isPending ? "Sending…" : `Send RFQ to ${selected.length}`}
          </Button>
        </div>
        {createMut.isError ? (
          <p className="mt-2 text-sm text-red-600">
            Failed to send RFQ: {createMut.error?.message ?? "unknown error"}
          </p>
        ) : null}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Active RFQs</h2>
          <div className="flex gap-1 text-xs">
            {(["", "draft", "sent", "responded", "closed"] as const).map((v) => (
              <button
                key={v || "all"}
                type="button"
                onClick={() => setStatusFilter(v)}
                className={`rounded-full border px-3 py-1 ${
                  statusFilter === v
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 text-slate-600 hover:bg-slate-100"
                }`}
              >
                {v || "All"}
              </button>
            ))}
          </div>
        </div>
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
              {visibleRfqs.map((r) => {
                const isExpanded = expandedId === r.id;
                const respondedCount = (r.responses ?? []).filter(
                  (e) => e?.status === "responded",
                ).length;
                return (
                  <>
                    <tr
                      key={r.id}
                      onClick={() => setExpandedId(isExpanded ? null : r.id)}
                      className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                    >
                      <td className="px-3 py-2 capitalize">
                        <span className="mr-2 inline-block w-3 text-slate-400">
                          {isExpanded ? "▾" : "▸"}
                        </span>
                        {r.status}
                      </td>
                      <td className="px-3 py-2">{r.sent_to.length}</td>
                      <td className="px-3 py-2">
                        {respondedCount} / {r.sent_to.length}
                      </td>
                      <td className="px-3 py-2">{r.deadline ?? "—"}</td>
                      <td className="px-3 py-2 text-slate-500">
                        {new Date(r.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr className="border-t border-slate-100 bg-slate-50">
                        <td colSpan={5} className="px-3 py-3">
                          <RfqResponsesPanel rfq={r} suppliers={suppliers?.items ?? []} />
                        </td>
                      </tr>
                    ) : null}
                  </>
                );
              })}
              {!isLoading && visibleRfqs.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-slate-500">
                    {statusFilter
                      ? `No RFQs with status "${statusFilter}".`
                      : "No RFQs yet."}
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
