"use client";

import Link from "next/link";
import { useState } from "react";
import { ClipboardCheck, Plus } from "lucide-react";

import { useCreatePunchList, usePunchLists } from "@/hooks/punchlist";
import type { PunchListListFilters } from "@/hooks/punchlist";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "open", label: "Đang mở" },
  { value: "in_review", label: "Đang xử lý" },
  { value: "signed_off", label: "Đã ký" },
  { value: "cancelled", label: "Đã huỷ" },
];

const STATUS_BADGE: Record<string, string> = {
  open: "bg-amber-100 text-amber-700",
  in_review: "bg-blue-100 text-blue-700",
  signed_off: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-zinc-100 text-zinc-600",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function PunchListPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [creating, setCreating] = useState(false);

  const filters: PunchListListFilters = {
    status:
      statusFilter === "all"
        ? undefined
        : (statusFilter as PunchListListFilters["status"]),
  };
  const { data, isLoading, isError } = usePunchLists(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Punch list</h2>
          <p className="text-sm text-slate-600">
            Danh sách kiểm tra của chủ đầu tư trong các buổi đi hiện trường —
            khác với defect (do bên thiết kế phát hiện).
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={16} />
          Tạo punch list
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
        <p className="text-sm text-red-600">Không thể tải danh sách.</p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <ClipboardCheck size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
          <p className="text-sm text-slate-500">Chưa có punch list nào.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((p) => {
            const completion =
              p.total_items > 0
                ? Math.round((p.verified_items / p.total_items) * 100)
                : 0;
            return (
              <Link
                key={p.id}
                href={`/punchlist/${p.id}`}
                className="block rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold text-slate-900">
                      {p.name}
                    </h3>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Khảo sát: {formatDate(p.walkthrough_date)}
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

                <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                  <Counter label="Tổng" value={p.total_items} tone="slate" />
                  <Counter
                    label="Mở"
                    value={p.open_items}
                    tone={p.open_items > 0 ? "amber" : "slate"}
                  />
                  <Counter
                    label="Đã xác minh"
                    value={p.verified_items}
                    tone="emerald"
                  />
                </div>

                <div className="mt-4 border-t border-slate-100 pt-3">
                  <div className="flex items-baseline justify-between text-[11px] text-slate-500">
                    <span>Hoàn tất</span>
                    <span className="font-medium text-slate-700">{completion}%</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full bg-emerald-500"
                      style={{ width: `${completion}%` }}
                    />
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {creating && <CreateDialog onClose={() => setCreating(false)} />}
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
  tone: "slate" | "amber" | "emerald";
}) {
  const colors: Record<typeof tone, string> = {
    slate: "text-slate-700 bg-slate-50",
    amber: "text-amber-700 bg-amber-50",
    emerald: "text-emerald-700 bg-emerald-50",
  };
  return (
    <div className={`rounded-md px-2 py-1.5 ${colors[tone]}`}>
      <p className="text-base font-semibold">{value}</p>
      <p className="text-[10px]">{label}</p>
    </div>
  );
}

function CreateDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [walkthroughDate, setWalkthroughDate] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [attendees, setAttendees] = useState("");
  const create = useCreatePunchList();

  const onSubmit = async () => {
    if (!projectId || !name) return;
    await create.mutateAsync({
      project_id: projectId,
      name,
      walkthrough_date: walkthroughDate,
      owner_attendees: attendees || undefined,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Tạo punch list</h3>
        <div className="mt-4 space-y-3">
          <input
            type="text"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="Mã dự án (UUID)"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tên punch list (vd: Pre-occupancy walkthrough)"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="date"
            value={walkthroughDate}
            onChange={(e) => setWalkthroughDate(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="text"
            value={attendees}
            onChange={(e) => setAttendees(e.target.value)}
            placeholder="Người tham gia"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
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
