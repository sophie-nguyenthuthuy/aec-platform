"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Calendar,
  CalendarClock,
  CheckCircle2,
  Clock,
  Filter,
  Layers,
  Loader2,
  ListTodo,
} from "lucide-react";

import {
  type AssigneeScope,
  type KindFilter,
  type StatusBucket,
  type WorkItem,
  useMyWorkList,
  useMyWorkSummary,
} from "@/hooks/my-work";


// ---------- Display dictionaries ----------
//
// Status strings come from the DB as English slugs; the UI is Vietnamese.
// Maps below convert per-source statuses to a tagged display label +
// pill colour. The two source modules (tasks + schedule_activities) have
// independent status enums so we cover both.
const TASK_STATUS_LABEL: Record<string, string> = {
  todo: "Chưa làm",
  in_progress: "Đang làm",
  review: "Đang duyệt",
  blocked: "Bị chặn",
  done: "Hoàn thành",
  cancelled: "Đã huỷ",
};
const ACTIVITY_STATUS_LABEL: Record<string, string> = {
  not_started: "Chưa bắt đầu",
  in_progress: "Đang làm",
  complete: "Hoàn thành",
  on_hold: "Tạm dừng",
};
const STATUS_PILL: Record<string, string> = {
  todo: "bg-slate-100 text-slate-700",
  not_started: "bg-slate-100 text-slate-700",
  in_progress: "bg-blue-100 text-blue-700",
  review: "bg-amber-100 text-amber-700",
  blocked: "bg-rose-100 text-rose-700",
  on_hold: "bg-amber-100 text-amber-700",
  done: "bg-emerald-100 text-emerald-700",
  complete: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-500",
};
const PRIORITY_LABEL: Record<string, string> = {
  low: "Thấp",
  normal: "Bình thường",
  high: "Cao",
  urgent: "Khẩn cấp",
};
const PRIORITY_PILL: Record<string, string> = {
  low: "bg-slate-100 text-slate-600",
  normal: "bg-slate-100 text-slate-700",
  high: "bg-amber-100 text-amber-700",
  urgent: "bg-rose-100 text-rose-700",
};
const KIND_LABEL: Record<string, string> = {
  task: "Việc",
  activity: "Tiến độ",
};


export default function MyWorkPage() {
  const [assignee, setAssignee] = useState<AssigneeScope>("anyone");
  const [status, setStatus] = useState<StatusBucket>("open");
  const [kind, setKind] = useState<KindFilter | null>(null);

  const list = useMyWorkList({
    assignee,
    status,
    kind: kind ?? undefined,
    limit: 100,
  });
  const summary = useMyWorkSummary(assignee);

  const grouped = useMemo(() => groupByProject(list.data?.items ?? []), [list.data]);

  return (
    <div className="space-y-6">
      {/* ---------- Page header ---------- */}
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Công việc đang thực hiện</h2>
        <p className="text-sm text-slate-600">
          Tổng hợp toàn bộ việc đang mở trên các dự án — kết hợp từ Pulse
          (kanban) và Tiến độ dự án (Gantt) để bạn biết hôm nay cần xử lý gì.
        </p>
      </div>

      {/* ---------- KPI tiles ---------- */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiTile
          icon={<ListTodo size={16} />}
          label="Đang mở"
          value={summary.data?.open ?? "—"}
          tone="default"
          loading={summary.isLoading}
        />
        <KpiTile
          icon={<AlertTriangle size={16} />}
          label="Quá hạn"
          value={summary.data?.overdue ?? "—"}
          tone="danger"
          loading={summary.isLoading}
        />
        <KpiTile
          icon={<CalendarClock size={16} />}
          label="Hôm nay"
          value={summary.data?.due_today ?? "—"}
          tone="warning"
          loading={summary.isLoading}
        />
        <KpiTile
          icon={<CheckCircle2 size={16} />}
          label="Hoàn thành (7 ngày)"
          value={summary.data?.completed_week ?? "—"}
          tone="success"
          loading={summary.isLoading}
        />
      </div>

      {/* ---------- Filter bar ---------- */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 bg-white p-3">
        <FilterGroup label="Phạm vi">
          <Toggle
            active={assignee === "anyone"}
            onClick={() => setAssignee("anyone")}
            label="Toàn công ty"
          />
          <Toggle
            active={assignee === "me"}
            onClick={() => setAssignee("me")}
            label="Của tôi"
          />
        </FilterGroup>

        <FilterGroup label="Trạng thái">
          <Toggle
            active={status === "open"}
            onClick={() => setStatus("open")}
            label="Đang mở"
          />
          <Toggle
            active={status === "overdue"}
            onClick={() => setStatus("overdue")}
            label="Quá hạn"
          />
          <Toggle
            active={status === "all"}
            onClick={() => setStatus("all")}
            label="Tất cả"
          />
        </FilterGroup>

        <FilterGroup label="Loại">
          <Toggle
            active={kind === null}
            onClick={() => setKind(null)}
            label="Cả hai"
          />
          <Toggle
            active={kind === "task"}
            onClick={() => setKind("task")}
            label="Việc"
          />
          <Toggle
            active={kind === "activity"}
            onClick={() => setKind("activity")}
            label="Tiến độ"
          />
        </FilterGroup>
      </div>

      {/* ---------- Row list ---------- */}
      {list.isLoading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải danh sách…
        </p>
      ) : list.isError ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          Không thể tải danh sách. Hãy thử lại sau hoặc liên hệ ops.
        </div>
      ) : (list.data?.items.length ?? 0) === 0 ? (
        <EmptyState assignee={assignee} status={status} />
      ) : (
        <div className="space-y-6">
          {grouped.map((group) => (
            <ProjectGroup
              key={group.projectId}
              projectId={group.projectId}
              projectName={group.projectName}
              items={group.items}
            />
          ))}
          {(list.data?.total ?? 0) > (list.data?.items.length ?? 0) && (
            <p className="text-xs text-slate-500">
              Đang hiển thị {list.data?.items.length}/{list.data?.total} mục.
              Lọc theo dự án hoặc thu hẹp trạng thái để xem rõ hơn.
            </p>
          )}
        </div>
      )}
    </div>
  );
}


// ---------- Helpers ----------


function groupByProject(items: WorkItem[]): Array<{
  projectId: string;
  projectName: string;
  items: WorkItem[];
}> {
  const map = new Map<string, { projectName: string; items: WorkItem[] }>();
  for (const it of items) {
    const existing = map.get(it.project_id);
    if (existing) {
      existing.items.push(it);
    } else {
      map.set(it.project_id, { projectName: it.project_name, items: [it] });
    }
  }
  return Array.from(map.entries()).map(([projectId, group]) => ({
    projectId,
    projectName: group.projectName,
    items: group.items,
  }));
}


// ---------- Subcomponents ----------


function KpiTile({
  icon,
  label,
  value,
  tone,
  loading,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  tone: "default" | "danger" | "warning" | "success";
  loading: boolean;
}) {
  const toneCls = {
    default: "text-slate-700",
    danger: "text-rose-700",
    warning: "text-amber-700",
    success: "text-emerald-700",
  }[tone];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-1 text-2xl font-semibold ${toneCls}`}>
        {loading ? <Loader2 size={18} className="animate-spin" /> : value}
      </p>
    </div>
  );
}


function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1 text-xs text-slate-500">
        <Filter size={11} />
        {label}:
      </span>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  );
}


function Toggle({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-blue-600 text-white"
          : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
      }`}
    >
      {label}
    </button>
  );
}


function ProjectGroup({
  projectId,
  projectName,
  items,
}: {
  projectId: string;
  projectName: string;
  items: WorkItem[];
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Layers size={14} className="text-slate-400" />
          <Link
            href={`/pulse/${projectId}` as never}
            className="text-sm font-medium text-slate-900 hover:underline"
          >
            {projectName}
          </Link>
          <span className="text-xs text-slate-500">({items.length} mục)</span>
        </div>
      </header>
      <ul className="divide-y divide-slate-100">
        {items.map((it) => (
          <li key={`${it.kind}:${it.id}`} className="px-4 py-3">
            <WorkRow item={it} />
          </li>
        ))}
      </ul>
    </section>
  );
}


function WorkRow({ item }: { item: WorkItem }) {
  const statusLabel =
    (item.kind === "task" ? TASK_STATUS_LABEL : ACTIVITY_STATUS_LABEL)[item.status] ||
    item.status;
  const statusCls = STATUS_PILL[item.status] || "bg-slate-100 text-slate-700";
  const overdue =
    item.due_date != null &&
    new Date(item.due_date) < new Date(new Date().toISOString().slice(0, 10));

  // Deep link target: tasks → /pulse/[project_id]/tasks, activities →
  // /schedule (the schedule list view; per-activity drill-down requires
  // the schedule id which we don't carry here).
  const href =
    item.kind === "task"
      ? (`/pulse/${item.project_id}/tasks` as const)
      : ("/schedule" as const);

  return (
    <div className="flex items-start gap-3">
      <span
        className={`mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
          item.kind === "task"
            ? "bg-violet-100 text-violet-700"
            : "bg-indigo-100 text-indigo-700"
        }`}
      >
        {KIND_LABEL[item.kind]}
      </span>
      <div className="flex-1">
        <Link
          href={href as never}
          className="block text-sm font-medium text-slate-900 hover:underline"
        >
          {item.title}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span className={`rounded-full px-1.5 py-0.5 ${statusCls}`}>{statusLabel}</span>
          {item.priority && (
            <span
              className={`rounded-full px-1.5 py-0.5 ${
                PRIORITY_PILL[item.priority] || "bg-slate-100 text-slate-600"
              }`}
            >
              {PRIORITY_LABEL[item.priority] || item.priority}
            </span>
          )}
          {item.due_date && (
            <span
              className={`inline-flex items-center gap-1 ${
                overdue ? "text-rose-600" : ""
              }`}
            >
              <Calendar size={11} />
              {formatVnDate(item.due_date)}
              {overdue && <AlertTriangle size={11} />}
            </span>
          )}
          {item.percent_complete != null && (
            <span className="inline-flex items-center gap-1">
              <Clock size={11} />
              {Math.round(item.percent_complete)}%
            </span>
          )}
          {item.assignee_email && (
            <span className="text-slate-400">→ {item.assignee_email}</span>
          )}
        </div>
      </div>
    </div>
  );
}


function EmptyState({
  assignee,
  status,
}: {
  assignee: AssigneeScope;
  status: StatusBucket;
}) {
  let msg = "Không có việc nào.";
  if (status === "overdue") {
    msg = assignee === "me"
      ? "Bạn không có việc nào quá hạn — tuyệt vời."
      : "Toàn công ty không có việc nào quá hạn — tuyệt vời.";
  } else if (assignee === "me") {
    msg = "Bạn chưa có việc nào đang mở.";
  }
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <CheckCircle2 size={32} className="mx-auto text-emerald-500" />
      <p className="mt-2 text-sm text-slate-600">{msg}</p>
    </div>
  );
}


function formatVnDate(iso: string): string {
  // ISO yyyy-mm-dd → dd/mm/yyyy. Standard Vietnamese date convention.
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
