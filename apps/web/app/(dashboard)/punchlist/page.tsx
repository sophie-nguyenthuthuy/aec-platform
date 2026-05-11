"use client";

import Link from "next/link";
import { useState } from "react";
import { ClipboardCheck, Plus } from "lucide-react";

import {
  Alert,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
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
  cancelled: "bg-muted text-muted-foreground",
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
      <PageHeader
        title="Punch list"
        description="Danh sách kiểm tra của chủ đầu tư trong các buổi đi hiện trường — khác với khiếm khuyết (do bên thiết kế phát hiện)."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo punch list
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
        <Alert variant="destructive">Không thể tải danh sách.</Alert>
      ) : !data?.data.length ? (
        <EmptyState
          icon={<ClipboardCheck size={20} />}
          title="Chưa có punch list nào."
        />
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
                className="block rounded-xl border bg-card p-5 transition hover:border-primary/40 hover:shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold text-foreground">
                      {p.name}
                    </h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Khảo sát: {formatDate(p.walkthrough_date)}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      STATUS_BADGE[p.status] ?? "bg-muted text-muted-foreground"
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

                <div className="mt-4 border-t pt-3">
                  <div className="flex items-baseline justify-between text-[11px] text-muted-foreground">
                    <span>Hoàn tất</span>
                    <span className="font-medium text-foreground">{completion}%</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
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
    slate: "text-foreground bg-muted/40",
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo punch list</h3>
        <div className="mt-4 space-y-3">
          <Input
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="Mã dự án (UUID)"
          />
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tên punch list (vd: Pre-occupancy walkthrough)"
          />
          <Input
            type="date"
            value={walkthroughDate}
            onChange={(e) => setWalkthroughDate(e.target.value)}
          />
          <Input
            value={attendees}
            onChange={(e) => setAttendees(e.target.value)}
            placeholder="Người tham gia"
          />
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
