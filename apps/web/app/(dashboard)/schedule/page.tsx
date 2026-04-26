"use client";

import Link from "next/link";
import { useState } from "react";
import { CalendarRange, Plus } from "lucide-react";

import { useCreateSchedule, useSchedules } from "@/hooks/schedule";
import type { ScheduleListFilters } from "@/hooks/schedule";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "baselined", label: "Đã chốt" },
  { value: "active", label: "Đang theo dõi" },
  { value: "archived", label: "Đã lưu trữ" },
];

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  baselined: "bg-amber-100 text-amber-700",
  active: "bg-blue-100 text-blue-700",
  archived: "bg-zinc-100 text-zinc-600",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function SchedulesPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [creating, setCreating] = useState(false);

  const filters: ScheduleListFilters = {
    status: statusFilter === "all" ? undefined : (statusFilter as ScheduleListFilters["status"]),
  };
  const { data, isLoading, isError } = useSchedules(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Tiến độ dự án</h2>
          <p className="text-sm text-slate-600">
            SchedulePilot — quản lý lịch CPM, baseline và phân tích rủi ro tiến
            độ bằng AI.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={16} />
          Tạo lịch mới
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setStatusFilter(f.value)}
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

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <p className="text-sm text-red-600">Không thể tải danh sách lịch.</p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <CalendarRange size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
          <p className="text-sm text-slate-500">Chưa có lịch nào.</p>
          <p className="mt-1 text-xs text-slate-400">
            Tạo một lịch mới để bắt đầu lập tiến độ và theo dõi baseline.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((s) => (
            <Link
              key={s.id}
              href={`/schedule/${s.id}`}
              className="block rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-slate-900">
                    {s.name}
                  </h3>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Data date: {formatDate(s.data_date)}
                    {s.baseline_set_at
                      ? ` · Baseline: ${formatDate(s.baseline_set_at)}`
                      : " · Chưa chốt baseline"}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    STATUS_BADGE[s.status] ?? "bg-slate-100 text-slate-700"
                  }`}
                >
                  {s.status}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
                <Counter label="Hoạt động" value={s.activity_count} tone="slate" />
                <Counter
                  label="Trễ tiến độ"
                  value={s.behind_schedule_count}
                  tone={s.behind_schedule_count > 0 ? "red" : "emerald"}
                />
                <Counter
                  label="Trên CPM"
                  value={s.on_critical_path_count}
                  tone="amber"
                />
              </div>

              <div className="mt-4 border-t border-slate-100 pt-3">
                <ProgressBar pct={s.percent_complete} />
              </div>
            </Link>
          ))}
        </div>
      )}

      {creating && <CreateScheduleDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function Counter({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "slate" | "red" | "emerald" | "amber";
}) {
  const colors: Record<typeof tone, string> = {
    slate: "text-slate-700 bg-slate-50",
    red: "text-red-700 bg-red-50",
    emerald: "text-emerald-700 bg-emerald-50",
    amber: "text-amber-700 bg-amber-50",
  };
  return (
    <div className={`rounded-md px-2 py-1.5 ${colors[tone]}`}>
      <p className="text-base font-semibold">{value}</p>
      <p className="text-[10px]">{label}</p>
    </div>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  const safe = Math.min(100, Math.max(0, pct));
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[11px] text-slate-500">
        <span>Tiến độ tổng</span>
        <span className="font-medium text-slate-700">{safe.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full bg-blue-500" style={{ width: `${safe}%` }} />
      </div>
    </div>
  );
}

function CreateScheduleDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const create = useCreateSchedule();

  const onSubmit = async () => {
    if (!projectId || !name) return;
    await create.mutateAsync({ project_id: projectId, name });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Tạo lịch mới</h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              Mã dự án
            </span>
            <input
              type="text"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="UUID dự án"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              Tên lịch
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Lịch tổng thể v1"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            Huỷ
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!projectId || !name || create.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </button>
        </div>
      </div>
    </div>
  );
}
