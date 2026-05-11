"use client";

import Link from "next/link";
import { useState } from "react";
import { CalendarRange, Plus } from "lucide-react";

import {
  Alert,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
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
  draft: "bg-muted text-muted-foreground",
  baselined: "bg-amber-100 text-amber-700",
  active: "bg-blue-100 text-blue-700",
  archived: "bg-muted text-muted-foreground",
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
      <PageHeader
        title="Tiến độ dự án"
        description="SchedulePilot — quản lý lịch CPM, baseline và phân tích rủi ro tiến độ bằng AI."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo lịch mới
          </Button>
        }
      />

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
            size="sm"
            variant={statusFilter === f.value ? "default" : "outline"}
            className="rounded-full"
            onClick={() => setStatusFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : isError ? (
        <Alert variant="destructive">Không thể tải danh sách lịch.</Alert>
      ) : !data?.data.length ? (
        <EmptyState
          icon={<CalendarRange size={20} />}
          title="Chưa có lịch nào."
          description="Tạo một lịch mới để bắt đầu lập tiến độ và theo dõi baseline."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((s) => (
            <Link
              key={s.id}
              href={`/schedule/${s.id}`}
              className="block rounded-xl border bg-card p-5 transition hover:border-primary/40 hover:shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold text-foreground">
                    {s.name}
                  </h3>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Data date: {formatDate(s.data_date)}
                    {s.baseline_set_at
                      ? ` · Baseline: ${formatDate(s.baseline_set_at)}`
                      : " · Chưa chốt baseline"}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    STATUS_BADGE[s.status] ?? "bg-muted text-muted-foreground"
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

              <div className="mt-4 border-t pt-3">
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
    slate: "text-foreground bg-muted/40",
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
      <div className="flex items-baseline justify-between text-[11px] text-muted-foreground">
        <span>Tiến độ tổng</span>
        <span className="font-medium text-foreground">{safe.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo lịch mới</h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Mã dự án
            </span>
            <Input
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="UUID dự án"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Tên lịch
            </span>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Lịch tổng thể v1"
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !name}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
