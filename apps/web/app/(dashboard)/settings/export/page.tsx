"use client";

import { useCallback, useState } from "react";
import {
  AlertTriangle,
  Download,
  FileSpreadsheet,
  Loader2,
  ShieldAlert,
} from "lucide-react";

import { useSession } from "@/lib/auth-context";


// Per-entity tab metadata. Mirrors the backend `EXPORT_CONFIGS` —
// adding an entity here without an entry there returns an empty CSV
// + a 422 from the path Literal, so the discrepancy is visible
// immediately. The filters list is the superset; the backend silently
// drops anything not in its per-entity allowlist.
type Entity = {
  value: string;
  label: string;
  description: string;
  filters: FilterDef[];
};

type FilterDef = {
  key: string;
  label: string;
  type: "select" | "text" | "date" | "uuid" | "bool";
  options?: Array<{ value: string; label: string }>;
};


const ENTITIES: Entity[] = [
  {
    value: "projects",
    label: "Dự án",
    description: "Mọi dự án trong tổ chức, kèm địa chỉ + ngân sách.",
    filters: [
      {
        key: "status",
        label: "Trạng thái",
        type: "select",
        options: [
          { value: "", label: "Tất cả" },
          { value: "planning", label: "Lập kế hoạch" },
          { value: "design", label: "Thiết kế" },
          { value: "bidding", label: "Đấu thầu" },
          { value: "construction", label: "Thi công" },
          { value: "handover", label: "Bàn giao" },
          { value: "completed", label: "Hoàn thành" },
        ],
      },
      { key: "type", label: "Loại", type: "text" },
    ],
  },
  {
    value: "suppliers",
    label: "Nhà cung cấp",
    description: "Sổ tay nhà cung cấp + danh mục + tỉnh phục vụ.",
    filters: [
      {
        key: "verified",
        label: "Đã xác minh",
        type: "select",
        options: [
          { value: "", label: "Tất cả" },
          { value: "true", label: "Đã xác minh" },
          { value: "false", label: "Chưa" },
        ],
      },
      { key: "province", label: "Tỉnh", type: "text" },
    ],
  },
  {
    value: "defects",
    label: "Lỗi (Defects)",
    description: "Snag list — các lỗi đã/đang được báo cáo từ Handover.",
    filters: [
      { key: "project_id", label: "Project ID", type: "uuid" },
      {
        key: "status",
        label: "Trạng thái",
        type: "select",
        options: [
          { value: "", label: "Tất cả" },
          { value: "open", label: "Mở" },
          { value: "in_progress", label: "Đang xử lý" },
          { value: "resolved", label: "Đã xử lý" },
          { value: "closed", label: "Đóng" },
        ],
      },
      {
        key: "priority",
        label: "Mức độ",
        type: "select",
        options: [
          { value: "", label: "Tất cả" },
          { value: "low", label: "Thấp" },
          { value: "medium", label: "Trung bình" },
          { value: "high", label: "Cao" },
          { value: "critical", label: "Khẩn" },
        ],
      },
      { key: "since", label: "Từ ngày (YYYY-MM-DD)", type: "date" },
    ],
  },
  {
    value: "change_orders",
    label: "Change orders",
    description: "Yêu cầu thay đổi thi công + giá trị tác động.",
    filters: [
      { key: "project_id", label: "Project ID", type: "uuid" },
      {
        key: "status",
        label: "Trạng thái",
        type: "select",
        options: [
          { value: "", label: "Tất cả" },
          { value: "draft", label: "Nháp" },
          { value: "submitted", label: "Đã nộp" },
          { value: "approved", label: "Đã duyệt" },
          { value: "rejected", label: "Từ chối" },
        ],
      },
      { key: "since", label: "Từ ngày", type: "date" },
    ],
  },
  {
    value: "rfis",
    label: "RFI",
    description: "Yêu cầu làm rõ thông tin (Request For Information).",
    filters: [
      { key: "project_id", label: "Project ID", type: "uuid" },
      {
        key: "status",
        label: "Trạng thái",
        type: "select",
        options: [
          { value: "", label: "Tất cả" },
          { value: "open", label: "Mở" },
          { value: "answered", label: "Đã trả lời" },
          { value: "closed", label: "Đóng" },
        ],
      },
      { key: "since", label: "Từ ngày", type: "date" },
    ],
  },
];


export default function ExportPage() {
  const { token, orgId } = useSession();
  const [entity, setEntity] = useState<string>("projects");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [format, setFormat] = useState<"csv" | "xlsx">("csv");
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const meta = ENTITIES.find((e) => e.value === entity)!;

  // Switching entity drops the filter state — different entities have
  // different allowed filter keys, and carrying a stale `priority`
  // chip onto the suppliers tab would be confusing.
  const switchEntity = useCallback((next: string) => {
    setEntity(next);
    setFilters({});
    setError(null);
  }, []);

  const downloadExport = useCallback(async () => {
    setDownloading(true);
    setError(null);
    try {
      // Build the query string from the filter dict — drop empty
      // values so the URL stays terse and the backend doesn't see
      // empty-string filters as "match empty".
      const params = new URLSearchParams({ format });
      for (const [k, v] of Object.entries(filters)) {
        if (v && v.trim()) params.append(k, v.trim());
      }
      const url = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/export/${entity}?${params.toString()}`;
      // We use `fetch` instead of an `<a href>` because Bearer auth
      // can't ride on an anchor click — there's no Authorization
      // header. Read the body as a Blob, mint an object URL, click a
      // synthetic <a download>, then revoke. Standard pattern for
      // header-authed downloads.
      const res = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Org-ID": orgId,
        },
      });
      if (!res.ok) {
        // Try to surface the JSON error envelope (admin guard, bad
        // filter); fall back to status text if the body isn't JSON.
        let msg = `${res.status} ${res.statusText}`;
        try {
          const json = await res.json();
          msg = json?.errors?.[0]?.message ?? msg;
        } catch {
          // not JSON — leave default
        }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const filename =
        res.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1] ??
        `aec-${entity}.${format}`;
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(objUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tải file thất bại.");
    } finally {
      setDownloading(false);
    }
  }, [entity, filters, format, token, orgId]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Xuất dữ liệu</h2>
        <p className="text-sm text-slate-600">
          Tải toàn bộ dữ liệu của tổ chức ra CSV / Excel. Idempotent với{" "}
          <a href="/settings/import" className="text-blue-600 hover:underline">
            trang nhập dữ liệu
          </a>{" "}
          — cột <code className="rounded bg-slate-100 px-1 text-xs">external_id</code>{" "}
          ở file xuất ra dùng được cho lần re-import sau.
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

      <p className="text-xs text-slate-500">{meta.description}</p>

      {/* ---------- Filters ---------- */}
      {meta.filters.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">Bộ lọc</h3>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
            {meta.filters.map((f) => (
              <FilterField
                key={f.key}
                def={f}
                value={filters[f.key] ?? ""}
                onChange={(v) =>
                  setFilters((prev) => ({ ...prev, [f.key]: v }))
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* ---------- Format + download ---------- */}
      <section className="flex flex-wrap items-end justify-between gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Định dạng
          </label>
          <div className="mt-1 flex gap-1.5">
            {(["csv", "xlsx"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFormat(f)}
                className={`inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium ${
                  format === f
                    ? "bg-slate-800 text-white"
                    : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-100"
                }`}
              >
                <FileSpreadsheet size={13} />
                {f.toUpperCase()}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            CSV: streaming, không giới hạn bộ nhớ. XLSX: tối đa 50.000 dòng.
          </p>
        </div>

        <button
          type="button"
          onClick={downloadExport}
          disabled={downloading}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {downloading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Download size={14} />
          )}
          Tải xuống
        </button>
      </section>

      {error && <ErrorBanner message={error} />}
    </div>
  );
}


// ---------- Sub-components ----------


function FilterField({
  def,
  value,
  onChange,
}: {
  def: FilterDef;
  value: string;
  onChange: (v: string) => void;
}) {
  const baseInputClass =
    "mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none";
  if (def.type === "select") {
    return (
      <div>
        <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {def.label}
        </label>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={baseInputClass}
        >
          {def.options?.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    );
  }
  return (
    <div>
      <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {def.label}
      </label>
      <input
        type={def.type === "date" ? "date" : "text"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={def.type === "uuid" ? "uuid" : ""}
        className={baseInputClass}
      />
    </div>
  );
}


function ErrorBanner({ message }: { message: string }) {
  // 403 → friendly admin-only hint; everything else → raw message.
  const isForbidden = /forbidden|403/i.test(message);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {isForbidden ? (
        <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      ) : (
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      )}
      <p>
        {isForbidden
          ? "Bạn cần quyền admin để xuất dữ liệu. Liên hệ owner."
          : message}
      </p>
    </div>
  );
}
