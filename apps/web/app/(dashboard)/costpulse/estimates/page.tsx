"use client";

import Link from "next/link";
import { useState } from "react";
import type { EstimateStatus } from "@aec/types";

import { Button } from "@aec/ui/primitives";
import { formatVnd } from "@aec/ui/costpulse";
import { useEstimates } from "@/hooks/costpulse";

export default function EstimateListPage(): JSX.Element {
  const [statusFilter, setStatusFilter] = useState<EstimateStatus | undefined>();
  const { data, isLoading, error } = useEstimates({ status: statusFilter });

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Estimates</h1>
        <Link href="/costpulse/estimates/new">
          <Button>New estimate</Button>
        </Link>
      </div>

      <div className="flex gap-2 text-sm">
        {(["", "draft", "approved", "superseded"] as const).map((v) => (
          <button
            key={v || "all"}
            type="button"
            onClick={() => setStatusFilter((v || undefined) as EstimateStatus | undefined)}
            className={`rounded-full border px-3 py-1 ${
              (statusFilter ?? "") === v
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-200 text-slate-600 hover:bg-slate-100"
            }`}
          >
            {v || "All"}
          </button>
        ))}
      </div>

      {isLoading && <div className="text-slate-500">Loading…</div>}
      {error && <div className="text-red-600">{error.message}</div>}

      <div className="overflow-hidden rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Method</th>
              <th className="px-3 py-2">Confidence</th>
              <th className="px-3 py-2 text-right">Total</th>
              <th className="px-3 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((e) => (
              <tr key={e.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-2">
                  <Link href={`/costpulse/estimates/${e.id}`} className="font-medium text-sky-700 hover:underline">
                    {e.name}
                  </Link>
                  <span className="ml-2 text-xs text-slate-500">v{e.version}</span>
                </td>
                <td className="px-3 py-2 capitalize">{e.status}</td>
                <td className="px-3 py-2 capitalize">{e.method?.replace("_", " ") ?? "—"}</td>
                <td className="px-3 py-2 capitalize">{e.confidence?.replace("_", " ") ?? "—"}</td>
                <td className="px-3 py-2 text-right font-semibold">{formatVnd(e.total_vnd)}</td>
                <td className="px-3 py-2 text-slate-500">{new Date(e.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
            {!isLoading && (data?.items.length ?? 0) === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-500">
                  No estimates yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
