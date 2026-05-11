"use client";

import Link from "next/link";
import { useState } from "react";
import { ClipboardList, Plus } from "lucide-react";

import {
  Alert,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useCreateDailyLog, useDailyLogs } from "@/hooks/dailylog";
import type { DailyLogListFilters } from "@/hooks/dailylog";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "submitted", label: "Đã nộp" },
  { value: "approved", label: "Đã duyệt" },
];

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
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
      <PageHeader
        title="Nhật ký công trường"
        description="Báo cáo hằng ngày về nhân lực, thiết bị, thời tiết và sự cố. AI tự động trích xuất rủi ro từ phần mô tả."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo nhật ký mới
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
        <Alert variant="destructive">Không thể tải danh sách nhật ký.</Alert>
      ) : !data?.data.length ? (
        <EmptyState
          icon={<ClipboardList size={20} />}
          title="Chưa có nhật ký công trường nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((l) => (
            <Link
              key={l.id}
              href={`/dailylog/${l.id}`}
              className="block rounded-xl border bg-card p-5 transition hover:border-primary/40 hover:shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-base font-semibold text-foreground">
                    {formatDate(l.log_date)}
                  </h3>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Tạo: {formatDate(l.created_at)}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    STATUS_BADGE[l.status] ?? "bg-muted text-muted-foreground"
                  }`}
                >
                  {l.status}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div className="rounded bg-muted/40 px-2 py-1.5">
                  <div className="text-muted-foreground">Nhân lực</div>
                  <p className="mt-0.5 text-base font-semibold text-foreground">
                    {l.total_headcount}
                  </p>
                </div>
                <div
                  className={`rounded px-2 py-1.5 ${
                    l.open_observations > 0 ? "bg-amber-50" : "bg-muted/40"
                  }`}
                >
                  <div className="text-muted-foreground">Vấn đề mở</div>
                  <p
                    className={`mt-0.5 text-base font-semibold ${
                      l.open_observations > 0 ? "text-amber-800" : "text-foreground"
                    }`}
                  >
                    {l.open_observations}
                  </p>
                </div>
                <div
                  className={`rounded px-2 py-1.5 ${
                    l.high_severity_observations > 0 ? "bg-red-50" : "bg-muted/40"
                  }`}
                >
                  <div className="text-muted-foreground">Nghiêm trọng</div>
                  <p
                    className={`mt-0.5 text-base font-semibold ${
                      l.high_severity_observations > 0
                        ? "text-destructive"
                        : "text-foreground"
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo nhật ký mới</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-foreground">Mã dự án</span>
            <Input value={projectId} onChange={(e) => setProjectId(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">Ngày</span>
            <Input
              type="date"
              value={logDate}
              onChange={(e) => setLogDate(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">Thời tiết</span>
            <Input
              value={conditions}
              onChange={(e) => setConditions(e.target.value)}
              placeholder="Nắng, có mây"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">Nhiệt độ (°C)</span>
            <Input
              type="number"
              value={tempC}
              onChange={(e) => setTempC(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">Mưa (mm)</span>
            <Input
              type="number"
              value={precipitation}
              onChange={(e) => setPrecipitation(e.target.value)}
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-foreground">Mô tả công việc / sự cố</span>
            <textarea
              rows={4}
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              placeholder="Đổ bê tông cột trục A-G tầng 3, mưa to làm chậm..."
            />
          </label>
          <label className="sm:col-span-2 flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={autoExtract}
              onChange={(e) => setAutoExtract(e.target.checked)}
              className="h-4 w-4 rounded border"
            />
            Tự động trích xuất rủi ro/vấn đề bằng AI
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !logDate}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
