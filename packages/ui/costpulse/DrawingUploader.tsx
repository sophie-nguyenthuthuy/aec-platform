"use client";

import { useCallback, useRef, useState } from "react";

import { cn } from "../lib/cn";
import { Button } from "../primitives/button";

export interface UploadedDrawing {
  file_id: string;
  name: string;
  size_bytes: number;
  mime_type: string | null;
  thumbnail_url: string | null;
}

export interface DrawingUploaderProps {
  /**
   * Called once per file. Must resolve with the uploaded file descriptor
   * (shape matches the hook `useUploadDrawing`). Throws on error; the
   * uploader catches and surfaces the message next to the row.
   */
  onUpload: (file: File) => Promise<UploadedDrawing>;
  onChange: (files: UploadedDrawing[]) => void;
  value: UploadedDrawing[];
  accept?: string;
  maxBytes?: number;
  className?: string;
}

type Row =
  | { kind: "queued"; tempId: string; name: string; size: number }
  | { kind: "uploading"; tempId: string; name: string; size: number; progress: number }
  | { kind: "error"; tempId: string; name: string; size: number; error: string }
  | { kind: "done"; tempId: string; uploaded: UploadedDrawing };

const DEFAULT_ACCEPT = "application/pdf,image/png,image/jpeg,image/webp";
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024;

/**
 * Drag-and-drop uploader for CostPulse "from-drawings" flow. Accepts PDFs and
 * images up to 25 MB, uploads them in parallel, and surfaces per-row progress
 * / errors. The parent only sees the committed list of UploadedDrawing[]
 * via `onChange` so its form state stays minimal.
 */
export function DrawingUploader({
  onUpload,
  onChange,
  value,
  accept = DEFAULT_ACCEPT,
  maxBytes = DEFAULT_MAX_BYTES,
  className,
}: DrawingUploaderProps): JSX.Element {
  const [rows, setRows] = useState<Row[]>(() =>
    value.map((v) => ({ kind: "done" as const, tempId: v.file_id, uploaded: v })),
  );
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const commit = useCallback(
    (next: Row[]) => {
      setRows(next);
      const done = next.flatMap((r) => (r.kind === "done" ? [r.uploaded] : []));
      onChange(done);
    },
    [onChange],
  );

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const incoming = Array.from(files);
      const rejected: Row[] = [];
      const accepted: { tempId: string; file: File }[] = [];

      for (const file of incoming) {
        const tempId = `tmp-${crypto.randomUUID()}`;
        if (file.size > maxBytes) {
          rejected.push({
            kind: "error",
            tempId,
            name: file.name,
            size: file.size,
            error: `File exceeds ${Math.floor(maxBytes / (1024 * 1024))} MB limit`,
          });
          continue;
        }
        accepted.push({ tempId, file });
      }

      let working: Row[] = [
        ...rows,
        ...rejected,
        ...accepted.map<Row>(({ tempId, file }) => ({
          kind: "uploading",
          tempId,
          name: file.name,
          size: file.size,
          progress: 0,
        })),
      ];
      commit(working);

      await Promise.all(
        accepted.map(async ({ tempId, file }) => {
          try {
            const uploaded = await onUpload(file);
            working = working.map((r) =>
              r.tempId === tempId
                ? ({ kind: "done", tempId, uploaded } as Row)
                : r,
            );
          } catch (err) {
            const message = err instanceof Error ? err.message : "Upload failed";
            working = working.map((r) =>
              r.tempId === tempId
                ? ({ kind: "error", tempId, name: file.name, size: file.size, error: message } as Row)
                : r,
            );
          }
          commit(working);
        }),
      );
    },
    [rows, maxBytes, onUpload, commit],
  );

  const remove = useCallback(
    (tempId: string) => {
      commit(rows.filter((r) => r.tempId !== tempId));
    },
    [rows, commit],
  );

  return (
    <div className={cn("space-y-3", className)}>
      <div
        onDragEnter={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length > 0) {
            void handleFiles(e.dataTransfer.files);
          }
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-8 text-center transition",
          dragging
            ? "border-sky-500 bg-sky-50"
            : "border-slate-300 bg-slate-50 hover:border-slate-400",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              void handleFiles(e.target.files);
              e.target.value = "";
            }
          }}
        />
        <div className="text-sm font-medium text-slate-700">
          Drop drawings here or click to browse
        </div>
        <div className="mt-1 text-xs text-slate-500">
          PDF, PNG, JPG, WEBP · up to {Math.floor(maxBytes / (1024 * 1024))} MB per file
        </div>
      </div>

      {rows.length > 0 && (
        <ul className="space-y-1.5">
          {rows.map((r) => (
            <li
              key={r.tempId}
              className="flex items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <RowIcon row={r} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-slate-800">
                  {r.kind === "done" ? r.uploaded.name : r.name}
                </div>
                <div className="text-xs text-slate-500">
                  {formatSize(r.kind === "done" ? r.uploaded.size_bytes : r.size)}
                  {r.kind === "uploading" && " · uploading…"}
                  {r.kind === "error" && (
                    <span className="text-red-600"> · {r.error}</span>
                  )}
                  {r.kind === "done" && (
                    <span className="text-emerald-600"> · uploaded</span>
                  )}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => remove(r.tempId)}
                disabled={r.kind === "uploading"}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RowIcon({ row }: { row: Row }): JSX.Element {
  const base =
    "flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-xs font-semibold";
  if (row.kind === "done") {
    return <div className={cn(base, "bg-emerald-100 text-emerald-700")}>✓</div>;
  }
  if (row.kind === "error") {
    return <div className={cn(base, "bg-red-100 text-red-700")}>!</div>;
  }
  if (row.kind === "uploading") {
    return (
      <div className={cn(base, "bg-sky-100 text-sky-700")}>
        <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-sky-500" />
      </div>
    );
  }
  return <div className={cn(base, "bg-slate-100 text-slate-600")}>…</div>;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
