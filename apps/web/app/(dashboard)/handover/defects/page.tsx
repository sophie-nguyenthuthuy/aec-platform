"use client";

import { useMemo, useState } from "react";
import { DefectCard } from "@aec/ui/handover";
import type { Defect, DefectPriority, DefectStatus } from "@aec/ui/handover";
import { useDefects, useUpdateDefect } from "@/hooks/handover";

const STATUS_COLUMNS: Array<{ value: DefectStatus; label: string }> = [
  { value: "open", label: "Mới" },
  { value: "assigned", label: "Đã giao" },
  { value: "in_progress", label: "Đang xử lý" },
  { value: "resolved", label: "Đã sửa" },
];

const PRIORITY_FILTERS: Array<{ value: DefectPriority | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "critical", label: "Khẩn cấp" },
  { value: "high", label: "Cao" },
  { value: "medium", label: "Trung bình" },
  { value: "low", label: "Thấp" },
];

export default function DefectsBoardPage() {
  const [priority, setPriority] = useState<DefectPriority | "all">("all");
  const { data, isLoading } = useDefects({
    priority: priority === "all" ? undefined : priority,
    limit: 200,
  });
  const update = useUpdateDefect();

  const byStatus = useMemo(() => {
    const map: Record<DefectStatus, Defect[]> = {
      open: [],
      assigned: [],
      in_progress: [],
      resolved: [],
      rejected: [],
    };
    for (const d of data?.data ?? []) {
      map[d.status]?.push(d);
    }
    return map;
  }, [data]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Bảng lỗi tồn đọng</h2>
        <p className="text-sm text-slate-600">
          Tổng hợp mọi lỗi cần xử lý qua các dự án bàn giao.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {PRIORITY_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setPriority(f.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              priority === f.value
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
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {STATUS_COLUMNS.map((col) => (
            <div
              key={col.value}
              className="rounded-lg bg-slate-100 p-3"
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">
                  {col.label}
                </h3>
                <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
                  {(byStatus[col.value] ?? []).length}
                </span>
              </div>
              <div className="space-y-2">
                {(byStatus[col.value] ?? []).map((d) => (
                  <DefectCard
                    key={d.id}
                    defect={d}
                    onStatusChange={(status) =>
                      update.mutate({ id: d.id, patch: { status } })
                    }
                  />
                ))}
                {(byStatus[col.value] ?? []).length === 0 && (
                  <p className="px-1 text-xs text-slate-500">Không có.</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
