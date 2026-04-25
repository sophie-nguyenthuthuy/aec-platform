"use client";

import Link from "next/link";
import { useState } from "react";
import { Building2, Search } from "lucide-react";

import { useProjects } from "@/hooks/projects";
import type { ProjectListFilters } from "@/hooks/projects";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "planning", label: "Lập kế hoạch" },
  { value: "design", label: "Thiết kế" },
  { value: "bidding", label: "Đấu thầu" },
  { value: "construction", label: "Thi công" },
  { value: "handover", label: "Bàn giao" },
  { value: "completed", label: "Hoàn thành" },
];

const STATUS_BADGE: Record<string, string> = {
  planning: "bg-slate-100 text-slate-700",
  design: "bg-indigo-100 text-indigo-700",
  bidding: "bg-amber-100 text-amber-700",
  construction: "bg-blue-100 text-blue-700",
  handover: "bg-purple-100 text-purple-700",
  completed: "bg-emerald-100 text-emerald-700",
  on_hold: "bg-yellow-100 text-yellow-700",
  cancelled: "bg-red-100 text-red-700",
};

function formatVnd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B ₫`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ₫`;
  return `${n.toLocaleString("vi-VN")} ₫`;
}

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function ProjectsPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const filters: ProjectListFilters = {
    status: statusFilter === "all" ? undefined : statusFilter,
    q: q || undefined,
    page,
  };

  const { data, isLoading, isError } = useProjects(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Dự án</h2>
          <p className="text-sm text-slate-600">
            Tổng quan toàn bộ dự án — nhấn vào một dự án để xem trạng thái từng
            module (CodeGuard, Drawbridge, CostPulse, Pulse, Handover, ...).
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            type="text"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Tìm theo tên dự án..."
            className="rounded-md border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => {
                setStatusFilter(f.value);
                setPage(1);
              }}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                statusFilter === f.value
                  ? "bg-blue-600 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <p className="text-sm text-red-600">
          Không thể tải danh sách dự án. Vui lòng thử lại.
        </p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <Building2
            size={32}
            className="mx-auto mb-3 text-slate-400"
            aria-hidden
          />
          <p className="text-sm text-slate-500">Chưa có dự án nào.</p>
          <p className="mt-1 text-xs text-slate-400">
            Dự án được tạo từ một đề xuất đã trúng (WinWork) hoặc nhập trực
            tiếp qua API.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.data.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="block rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold text-slate-900">
                      {p.name}
                    </h3>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {p.type ?? "—"} ·{" "}
                      {[p.address?.district, p.address?.city]
                        .filter(Boolean)
                        .join(", ") || "—"}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      STATUS_BADGE[p.status] ?? "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {p.status}
                  </span>
                </div>

                <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <dt className="text-slate-500">Ngân sách</dt>
                    <dd className="mt-0.5 font-medium text-slate-800">
                      {formatVnd(p.budget_vnd)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Khởi công</dt>
                    <dd className="mt-0.5 font-medium text-slate-800">
                      {formatDate(p.start_date)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Diện tích</dt>
                    <dd className="mt-0.5 font-medium text-slate-800">
                      {p.area_sqm ? `${p.area_sqm.toLocaleString("vi-VN")} m²` : "—"}
                    </dd>
                  </div>
                </dl>

                <div className="mt-4 flex items-center gap-3 border-t border-slate-100 pt-3 text-[11px]">
                  <CounterPill label="Tasks mở" value={p.open_tasks} tone="blue" />
                  <CounterPill
                    label="CO mở"
                    value={p.open_change_orders}
                    tone="amber"
                  />
                  <CounterPill label="Tài liệu" value={p.document_count} tone="slate" />
                </div>
              </Link>
            ))}
          </div>

          {data.meta && data.meta.total != null && data.meta.per_page != null && (
            <Pagination
              page={page}
              perPage={data.meta.per_page}
              total={data.meta.total}
              onPageChange={setPage}
            />
          )}
        </>
      )}
    </div>
  );
}

function CounterPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "blue" | "amber" | "slate";
}) {
  const colors: Record<typeof tone, string> = {
    blue: "text-blue-700 bg-blue-50",
    amber: "text-amber-700 bg-amber-50",
    slate: "text-slate-700 bg-slate-50",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 ${colors[tone]}`}>
      <span className="font-semibold">{value}</span>
      <span>{label}</span>
    </span>
  );
}

function Pagination({
  page,
  perPage,
  total,
  onPageChange,
}: {
  page: number;
  perPage: number;
  total: number;
  onPageChange: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between border-t border-slate-100 pt-4 text-xs text-slate-600">
      <span>
        Trang {page} / {totalPages} · {total} dự án
      </span>
      <div className="flex gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="rounded border border-slate-200 px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
        >
          Trước
        </button>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="rounded border border-slate-200 px-3 py-1 hover:bg-slate-50 disabled:opacity-50"
        >
          Sau
        </button>
      </div>
    </div>
  );
}
