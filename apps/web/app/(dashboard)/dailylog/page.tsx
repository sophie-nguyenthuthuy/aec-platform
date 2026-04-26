"use client";

import Link from "next/link";
import { useState } from "react";
import { Cloud, ClipboardList, Plus, Users } from "lucide-react";

import { useCreateDailyLog, useDailyLogs } from "@/hooks/dailylog";
import type { DailyLogListFilters } from "@/hooks/dailylog";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "submitted", label: "Đã nộp" },
  { value: "approved", label: "Đã duyệt" },
];

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  submitted: "bg-blue-100 text-blue-700",
  approved: "bg-emerald-100 text-emerald-700",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function DailyLogPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [creating, setCreating] = useState(false);

  const filters: DailyLogListFilters = {
    status:
      statusFilter === "all"
        ? undefined
        : (statusFilter as DailyLogListFilters["status"]),
  };
  const { data, isLoading, isError } = useDailyLogs(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Nhật ký công trường</h2>
          <p className="text-sm text-slate-600">
            Báo cáo hằng ngày về nhân lực, thiết bị, thời tiết và sự cố. AI
            tự động trích xuất rủi ro từ phần mô tả.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={16} />
          Tạo nhật ký mới
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
        <p className="text-sm text-red-600">Không thể tải danh sách nhật ký.</p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <ClipboardList size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
          <p className="text-sm text-slate-500">Chưa có nhật ký công trường nào.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((l) => (
            <Link
              key={l.id}
              href={`/dailylog/${l.id}`}
              className="block rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-base font-semibold text-slate-900">
                    {formatDate(l.log_date)}
                  </h3>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Tạo: {formatDate(l.created_at)}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    STATUS_BADGE[l.status] ?? "bg-slate-100 text-slate-700"
                  }`}
                >
                  {l.status}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div className="rounded bg-slate-50 px-2 py-1.5">
                  <div className="flex items-center gap-1 text-slate-500">
                    <Users size={11} /> Nhân lực
                  </div>
                  <p className="mt-0.5 text-base font-semibold text-slate-900">
                    {l.total_headcount}
                  </p>
                </div>
                <div
                  className={`rounded px-2 py-1.5 ${
                    l.open_observations > 0 ? "bg-amber-50" : "bg-slate-50"
                  }`}
                >
                  <div className="text-slate-500">Vấn đề mở</div>
                  <p
                    className={`mt-0.5 text-base font-semibold ${
                      l.open_observations > 0 ? "text-amber-800" : "text-slate-900"
                    }`}
                  >
                    {l.open_observations}
                  </p>
                </div>
                <div
                  className={`rounded px-2 py-1.5 ${
                    l.high_severity_observations > 0 ? "bg-red-50" : "bg-slate-50"
                  }`}
                >
                  <div className="text-slate-500">Nghiêm trọng</div>
                  <p
                    className={`mt-0.5 text-base font-semibold ${
                      l.high_severity_observations > 0
                        ? "text-red-800"
                        : "text-slate-900"
                    }`}
                  >
                    {l.high_severity_observations}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {creating && <CreateLogDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateLogDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [narrative, setNarrative] = useState("");
  const [tempC, setTempC] = useState("");
  const [precipitation, setPrecipitation] = useState("");
  const [conditions, setConditions] = useState("");
  const [autoExtract, setAutoExtract] = useState(true);
  const create = useCreateDailyLog();

  const onSubmit = async () => {
    if (!projectId || !logDate) return;
    await create.mutateAsync({
      project_id: projectId,
      log_date: logDate,
      narrative: narrative || undefined,
      weather: {
        temp_c: tempC ? Number(tempC) : undefined,
        precipitation_mm: precipitation ? Number(precipitation) : undefined,
        conditions: conditions || undefined,
      },
      auto_extract: autoExtract,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Tạo nhật ký mới</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-slate-700">Mã dự án</span>
            <input
              type="text"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Ngày</span>
            <input
              type="date"
              value={logDate}
              onChange={(e) => setLogDate(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Thời tiết</span>
            <input
              type="text"
              value={conditions}
              onChange={(e) => setConditions(e.target.value)}
              placeholder="Nắng, có mây"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Nhiệt độ (°C)</span>
            <input
              type="number"
              value={tempC}
              onChange={(e) => setTempC(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Mưa (mm)</span>
            <input
              type="number"
              value={precipitation}
              onChange={(e) => setPrecipitation(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-slate-700">Mô tả công việc / sự cố</span>
            <textarea
              rows={4}
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="Đổ bê tông cột trục A-G tầng 3, mưa to làm chậm..."
            />
          </label>
          <label className="sm:col-span-2 flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={autoExtract}
              onChange={(e) => setAutoExtract(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Tự động trích xuất rủi ro/vấn đề bằng AI
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
            disabled={!projectId || !logDate || create.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </button>
        </div>
      </div>
    </div>
  );
}
