"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import type { BoqItemInput, UUID } from "@aec/types";

import { Button } from "@aec/ui/primitives";
import {
  BOQTable,
  ConfidenceMeter,
  ExportBOQ,
  formatVnd,
} from "@aec/ui/costpulse";
import {
  useApproveEstimate,
  useEstimate,
  useUpdateBoq,
} from "@/hooks/costpulse";

export default function EstimateEditorPage(): JSX.Element {
  const params = useParams<{ id: string }>();
  const id = params.id as UUID;

  const { data: estimate, isLoading, error } = useEstimate(id);
  const updateMut = useUpdateBoq(id);
  const approveMut = useApproveEstimate(id);

  const [pending, setPending] = useState<BoqItemInput[] | null>(null);
  const isReadOnly = estimate?.status === "approved";

  if (isLoading) return <div className="p-6 text-slate-500">Loading…</div>;
  if (error) return <div className="p-6 text-red-600">{error.message}</div>;
  if (!estimate) return <div className="p-6">Not found.</div>;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{estimate.name}</h1>
          <div className="mt-1 text-sm text-slate-500">
            v{estimate.version} · <span className="capitalize">{estimate.status}</span>
            {estimate.method && <> · {estimate.method.replace("_", " ")}</>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="text-xs uppercase tracking-wide text-slate-500">Total</div>
          <div className="text-3xl font-bold text-slate-900">{formatVnd(estimate.total_vnd)}</div>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <ConfidenceMeter confidence={estimate.confidence} />
        </div>
        <div className="flex items-center justify-end gap-2 rounded-lg border border-slate-200 bg-white p-4">
          <ExportBOQ estimate={estimate} items={estimate.items} />
          {!isReadOnly && (
            <Button
              variant="outline"
              onClick={() => approveMut.mutate()}
              disabled={approveMut.isPending}
            >
              {approveMut.isPending ? "Approving…" : "Approve"}
            </Button>
          )}
        </div>
      </div>

      <BOQTable
        items={estimate.items}
        editable={!isReadOnly}
        onChange={(items) => setPending(items)}
      />

      {!isReadOnly && (
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => setPending(null)}
            disabled={!pending || updateMut.isPending}
          >
            Discard changes
          </Button>
          <Button
            onClick={async () => {
              if (pending) {
                await updateMut.mutateAsync(pending as typeof estimate.items);
                setPending(null);
              }
            }}
            disabled={!pending || updateMut.isPending}
          >
            {updateMut.isPending ? "Saving…" : "Save BOQ"}
          </Button>
        </div>
      )}
    </div>
  );
}
