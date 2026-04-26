"use client";

import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import type { BoqItemInput, UUID } from "@aec/types";

import { Button } from "@aec/ui/primitives";
import {
  BOQTable,
  ConfidenceMeter,
  formatVnd,
} from "@aec/ui/costpulse";
import {
  useApproveEstimate,
  useEstimate,
  useExportBoq,
  useImportBoq,
  useUpdateBoq,
} from "@/hooks/costpulse";

export default function EstimateEditorPage(): JSX.Element {
  const params = useParams<{ id: string }>();
  const id = params.id as UUID;

  const { data: estimate, isLoading, error } = useEstimate(id);
  const updateMut = useUpdateBoq(id);
  const approveMut = useApproveEstimate(id);
  const importMut = useImportBoq(id);
  const downloadBoq = useExportBoq(id);

  const [pending, setPending] = useState<BoqItemInput[] | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
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
        <div className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-end gap-2">
            {!isReadOnly && (
              <>
                {/* Hidden file input so we can style the trigger as a Button. */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  className="hidden"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    // Reset the input so picking the same file twice still
                    // fires onChange — otherwise the browser sees no change.
                    e.target.value = "";
                    if (!file) return;
                    try {
                      await importMut.mutateAsync(file);
                    } catch {
                      // mutation surfaces the message in importMut.error;
                      // no need to re-throw and crash the dialog.
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importMut.isPending}
                >
                  {importMut.isPending ? "Importing…" : "Import .xlsx"}
                </Button>
              </>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                setExportError(null);
                try {
                  await downloadBoq("xlsx");
                } catch (e) {
                  setExportError(e instanceof Error ? e.message : "Export failed");
                }
              }}
            >
              Export .xlsx
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                setExportError(null);
                try {
                  await downloadBoq("pdf");
                } catch (e) {
                  setExportError(e instanceof Error ? e.message : "Export failed");
                }
              }}
            >
              Export .pdf
            </Button>
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
          {importMut.isError ? (
            <p className="text-right text-xs text-red-600">
              Import failed: {importMut.error?.message ?? "unknown error"}
            </p>
          ) : null}
          {exportError ? (
            <p className="text-right text-xs text-red-600">
              {exportError}
            </p>
          ) : null}
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
