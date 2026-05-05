"use client";

import { useCallback, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  Upload,
  XCircle,
} from "lucide-react";

import {
  type ImportEntity,
  type ImportJobSummary,
  useImportCommit,
  useImportPreview,
} from "@/hooks/imports";


// Per-entity user-facing copy: tab label + the column hint shown
// inline above the drop-zone. Mirrors the validators on the backend
// (`services/imports.py`); change one and the other won't notice
// until a user uploads a mis-shaped sheet, so the README in the
// service file calls this out explicitly.
const ENTITIES: Array<{
  value: ImportEntity;
  label: string;
  required: string[];
  optional: string[];
}> = [
  {
    value: "projects",
    label: "Dự án",
    required: ["external_id", "name"],
    optional: [
      "type",
      "status",
      "city",
      "district",
      "area_sqm",
      "budget_vnd",
      "floors",
    ],
  },
  {
    value: "suppliers",
    label: "Nhà cung cấp",
    required: ["external_id", "name"],
    optional: [
      "categories",
      "provinces",
      "phone",
      "email",
      "address",
      "verified",
    ],
  },
];


export default function ImportPage() {
  const [entity, setEntity] = useState<ImportEntity>("projects");
  const [job, setJob] = useState<ImportJobSummary | null>(null);
  const [committed, setCommitted] = useState<{ count: number } | null>(null);

  const preview = useImportPreview();
  const commit = useImportCommit();

  // Reset the in-page state when the entity tab flips. Otherwise a
  // preview from the projects tab would linger when the user clicks
  // suppliers, which is confusing.
  //
  // The DropZone receives `entity` as its React `key` so it remounts
  // on switch — that's the simplest way to clear the underlying
  // <input type="file">, whose value can't be set programmatically
  // for security reasons.
  const switchEntity = useCallback((next: ImportEntity) => {
    setEntity(next);
    setJob(null);
    setCommitted(null);
    preview.reset();
    commit.reset();
  }, [preview, commit]);

  const handleFile = useCallback(
    (file: File | null) => {
      if (!file) return;
      setCommitted(null);
      preview.mutate(
        { entity, file },
        {
          onSuccess: (data) => setJob(data),
          onError: () => setJob(null),
        },
      );
    },
    [entity, preview],
  );

  const handleCommit = useCallback(() => {
    if (!job) return;
    commit.mutate(job.id, {
      onSuccess: (data) => {
        setCommitted({ count: data.committed_count });
      },
    });
  }, [commit, job]);

  const meta = ENTITIES.find((e) => e.value === entity)!;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Nhập dữ liệu</h2>
        <p className="text-sm text-slate-600">
          Tải lên CSV hoặc Excel để nạp hàng loạt dự án / nhà cung cấp. Idempotent
          theo cột <code className="rounded bg-slate-100 px-1 text-xs">external_id</code>{" "}
          — tải lại cùng file sẽ cập nhật, không tạo trùng.
        </p>
      </div>

      {/* ---------- Entity tabs ---------- */}
      <div className="flex flex-wrap gap-1.5">
        {ENTITIES.map((e) => (
          <button
            key={e.value}
            type="button"
            onClick={() => switchEntity(e.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              entity === e.value
                ? "bg-blue-600 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {e.label}
          </button>
        ))}
      </div>

      {/* ---------- Schema hint ---------- */}
      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
        <p className="font-medium text-slate-700">
          Cột bắt buộc:{" "}
          {meta.required.map((c, i) => (
            <span key={c}>
              {i > 0 && ", "}
              <code className="rounded bg-white px-1 ring-1 ring-slate-200">{c}</code>
            </span>
          ))}
        </p>
        <p className="mt-1.5 text-slate-500">
          Cột tuỳ chọn:{" "}
          {meta.optional.map((c, i) => (
            <span key={c}>
              {i > 0 && ", "}
              <code className="rounded bg-white px-1 ring-1 ring-slate-200">{c}</code>
            </span>
          ))}
        </p>
        <p className="mt-2 text-[11px] text-slate-500">
          Tối đa 1000 hàng / lần. Hỗ trợ <code>.csv</code>, <code>.xlsx</code>.
          Header tự normalise (case-insensitive, khoảng trắng → underscore).
        </p>
      </section>

      {/* ---------- Drop zone ---------- */}
      <DropZone
        key={entity}
        disabled={preview.isPending}
        onFile={handleFile}
      />

      {/* ---------- Preview / commit state machine ---------- */}
      {preview.isPending ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang phân tích file...
        </p>
      ) : preview.isError ? (
        <ErrorBanner message={(preview.error as Error)?.message ?? "Tải file thất bại."} />
      ) : job && committed ? (
        <CommitSuccess count={committed.count} entityLabel={meta.label} />
      ) : job ? (
        <PreviewPanel
          job={job}
          onCommit={handleCommit}
          committing={commit.isPending}
          commitError={(commit.error as Error | null)?.message ?? null}
        />
      ) : null}
    </div>
  );
}


// ---------- Drop zone ----------


/**
 * File-input + drag-and-drop. Wraps a hidden `<input type="file">`
 * so we still get OS-native file pickers; drag-and-drop is icing.
 *
 * The page passes `entity` as a React `key` so this component
 * remounts on tab switch — that resets the `<input>`'s `value` for
 * us (browsers don't let JS write to it). Otherwise the same file
 * dropped on a different entity wouldn't re-fire `change`.
 */
function DropZone({
  onFile,
  disabled,
}: {
  onFile: (f: File | null) => void;
  disabled: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setHover(false);
        if (disabled) return;
        const file = e.dataTransfer.files[0] ?? null;
        onFile(file);
      }}
      className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-10 text-center transition ${
        hover
          ? "border-blue-400 bg-blue-50"
          : "border-slate-300 bg-white hover:border-slate-400"
      } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    >
      <input
        type="file"
        accept=".csv,.xlsx,.xlsm"
        disabled={disabled}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        className="hidden"
      />
      <Upload size={24} className="text-slate-400" />
      <p className="text-sm font-medium text-slate-700">
        Kéo file vào đây, hoặc nhấn để chọn
      </p>
      <p className="text-[11px] text-slate-500">.csv, .xlsx, .xlsm — tối đa 5MB</p>
    </label>
  );
}


// ---------- Preview panel ----------


function PreviewPanel({
  job,
  onCommit,
  committing,
  commitError,
}: {
  job: ImportJobSummary;
  onCommit: () => void;
  committing: boolean;
  commitError: string | null;
}) {
  const canCommit = job.valid_count > 0 && !committing;
  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileSpreadsheet size={16} className="text-slate-400" />
          <span className="text-sm font-medium text-slate-800">
            {job.filename}
          </span>
        </div>
        <button
          type="button"
          onClick={onCommit}
          disabled={!canCommit}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {committing ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <CheckCircle2 size={14} />
          )}
          Commit {job.valid_count} hàng
        </button>
      </header>

      <div className="grid gap-2 sm:grid-cols-3">
        <Tile
          tone="blue"
          label="Tổng số hàng"
          value={job.row_count.toLocaleString("vi-VN")}
        />
        <Tile
          tone="emerald"
          label="Hợp lệ"
          value={job.valid_count.toLocaleString("vi-VN")}
        />
        <Tile
          tone={job.error_count > 0 ? "amber" : "slate"}
          label="Lỗi"
          value={job.error_count.toLocaleString("vi-VN")}
        />
      </div>

      {job.errors.length > 0 && <ErrorList errors={job.errors} />}

      {commitError && <ErrorBanner message={commitError} />}
    </section>
  );
}


function Tile({
  tone,
  label,
  value,
}: {
  tone: "blue" | "emerald" | "amber" | "slate";
  label: string;
  value: string;
}) {
  const map: Record<typeof tone, string> = {
    blue: "border-blue-200 bg-blue-50 text-blue-900",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    slate: "border-slate-200 bg-slate-50 text-slate-700",
  };
  return (
    <div className={`rounded-lg border p-3 ${map[tone]}`}>
      <p className="text-[11px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-0.5 text-xl font-semibold">{value}</p>
    </div>
  );
}


function ErrorList({ errors }: { errors: ImportJobSummary["errors"] }) {
  // Cap the rendered list at 50 to keep the DOM small. The full count
  // is shown in the tile above; users with thousands of errors should
  // fix the spreadsheet, not scroll.
  const shown = errors.slice(0, 50);
  const overflow = errors.length - shown.length;
  return (
    <details className="rounded-lg border border-amber-200 bg-amber-50/50">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-amber-900">
        Xem {errors.length} lỗi
      </summary>
      <ul className="divide-y divide-amber-100">
        {shown.map((e) => (
          <li
            key={`${e.row_idx}-${e.message}`}
            className="flex items-start gap-2 px-3 py-1.5 text-xs"
          >
            <span className="font-mono text-amber-700 tabular-nums">
              Hàng {e.row_idx}
            </span>
            <span className="text-slate-700">{e.message}</span>
          </li>
        ))}
        {overflow > 0 && (
          <li className="px-3 py-2 text-xs text-amber-700">
            ... và {overflow} lỗi nữa. Sửa trong file gốc và tải lại.
          </li>
        )}
      </ul>
    </details>
  );
}


function CommitSuccess({ count, entityLabel }: { count: number; entityLabel: string }) {
  return (
    <section className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-emerald-600" />
      <div>
        <p className="text-sm font-semibold text-emerald-900">
          Đã commit thành công {count.toLocaleString("vi-VN")} {entityLabel.toLowerCase()}.
        </p>
        <p className="mt-0.5 text-xs text-emerald-700">
          Bạn có thể tải file khác lên hoặc đóng trang. Re-uploading the same file
          sẽ cập nhật rows hiện có (idempotent qua external_id).
        </p>
      </div>
    </section>
  );
}


function ErrorBanner({ message }: { message: string }) {
  // 403 sneaks through as a plain English error from apiFetch; map
  // the most common one to a friendlier hint without trying to parse
  // status codes (the hook just throws Error).
  const friendly = /forbidden|403/i.test(message)
    ? "Bạn cần quyền admin để nhập dữ liệu. Liên hệ owner."
    : message;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {/forbidden|403/i.test(message) ? (
        <XCircle size={16} className="mt-0.5 shrink-0" />
      ) : (
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      )}
      <p>{friendly}</p>
    </div>
  );
}
