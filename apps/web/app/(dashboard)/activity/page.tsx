"use client";

import Link from "next/link";
import type { Route } from "next";
import { useState } from "react";
import {
  AlertTriangle,
  BookCheck,
  CheckCircle2,
  ClipboardList,
  FileText,
  HardHat,
  PackageCheck,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import {
  Alert,
  Button,
  EmptyState,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useActivityFeed } from "@/hooks/activity";
import type {
  ActivityEvent,
  ActivityEventType,
  ActivityModule,
} from "@aec/types/activity";

const MODULE_FILTERS: Array<{ value: "all" | ActivityModule; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "pulse", label: "Pulse" },
  { value: "siteeye", label: "SiteEye" },
  { value: "handover", label: "Handover" },
  { value: "winwork", label: "WinWork" },
  { value: "drawbridge", label: "Drawbridge" },
  { value: "costpulse", label: "CostPulse" },
];

const WINDOW_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 1, label: "Hôm nay" },
  { value: 7, label: "7 ngày" },
  { value: 30, label: "30 ngày" },
  { value: 90, label: "90 ngày" },
];

interface ModuleVisuals {
  icon: LucideIcon;
  badgeClass: string;
  iconClass: string;
}

const MODULE_VISUALS: Record<ActivityModule, ModuleVisuals> = {
  pulse: {
    icon: CheckCircle2,
    badgeClass: "bg-blue-100 text-blue-800",
    iconClass: "bg-blue-500",
  },
  siteeye: {
    icon: HardHat,
    badgeClass: "bg-orange-100 text-orange-800",
    iconClass: "bg-orange-500",
  },
  handover: {
    icon: PackageCheck,
    badgeClass: "bg-purple-100 text-purple-800",
    iconClass: "bg-purple-500",
  },
  winwork: {
    icon: BookCheck,
    badgeClass: "bg-emerald-100 text-emerald-800",
    iconClass: "bg-emerald-500",
  },
  drawbridge: {
    icon: FileText,
    badgeClass: "bg-indigo-100 text-indigo-800",
    iconClass: "bg-indigo-500",
  },
  costpulse: {
    icon: Wallet,
    badgeClass: "bg-amber-100 text-amber-800",
    iconClass: "bg-amber-500",
  },
  codeguard: {
    icon: AlertTriangle,
    badgeClass: "bg-rose-100 text-rose-800",
    iconClass: "bg-rose-500",
  },
};

const EVENT_LABEL: Record<ActivityEventType, string> = {
  change_order_created: "Change order",
  task_completed: "Task hoàn thành",
  safety_incident_detected: "Sự cố an toàn",
  defect_reported: "Lỗi tồn đọng",
  proposal_outcome_marked: "Đề xuất",
  rfi_raised: "RFI",
  handover_package_delivered: "Bàn giao",
};

function formatRelative(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} giờ trước`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} ngày trước`;
  return new Date(iso).toLocaleDateString("vi-VN");
}

export default function ActivityPage() {
  const [moduleFilter, setModuleFilter] = useState<"all" | ActivityModule>(
    "all",
  );
  const [windowDays, setWindowDays] = useState<number>(30);

  const { data, isLoading, isError } = useActivityFeed({
    module: moduleFilter === "all" ? undefined : moduleFilter,
    since_days: windowDays,
  });

  const events = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Hoạt động"
        description="Dòng sự kiện theo thời gian thực qua tất cả các module — change order, task hoàn thành, sự cố an toàn, lỗi tồn đọng, RFI..."
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1.5">
          {MODULE_FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={moduleFilter === f.value ? "default" : "outline"}
              className="rounded-full"
              onClick={() => setModuleFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">·</span>
        <div className="flex flex-wrap gap-1.5">
          {WINDOW_OPTIONS.map((w) => (
            <Button
              key={w.value}
              size="sm"
              variant={windowDays === w.value ? "secondary" : "outline"}
              className="rounded-full"
              onClick={() => setWindowDays(w.value)}
            >
              {w.label}
            </Button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : isError ? (
        <Alert variant="destructive">Không thể tải dòng hoạt động.</Alert>
      ) : events.length === 0 ? (
        <EmptyState
          icon={<ClipboardList size={20} />}
          title="Không có hoạt động nào trong khoảng thời gian này."
        />
      ) : (
        <ol className="relative space-y-4 border-l pl-6">
          {events.map((e) => (
            <ActivityRow key={`${e.module}-${e.id}`} event={e} />
          ))}
        </ol>
      )}

      {data?.meta?.total != null && events.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {events.length} / {data.meta.total} sự kiện
        </p>
      )}
    </div>
  );
}

function ActivityRow({ event }: { event: ActivityEvent }) {
  const visuals = MODULE_VISUALS[event.module];
  const Icon = visuals.icon;

  return (
    <li className="relative">
      <span
        className={`absolute -left-9 top-2 flex h-6 w-6 items-center justify-center rounded-full ${visuals.iconClass}`}
        aria-hidden
      >
        <Icon size={12} className="text-white" />
      </span>
      <div className="rounded-xl border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span
                className={`rounded-full px-2 py-0.5 font-medium uppercase tracking-wide ${visuals.badgeClass}`}
              >
                {event.module}
              </span>
              <span className="text-muted-foreground">·</span>
              <span>{EVENT_LABEL[event.event_type]}</span>
              {event.project_id && event.project_name && (
                <>
                  <span className="text-muted-foreground">·</span>
                  <Link
                    href={`/projects/${event.project_id}` as Route}
                    className="text-primary hover:underline"
                  >
                    {event.project_name}
                  </Link>
                </>
              )}
              <span className="text-muted-foreground">·</span>
              <span>{formatRelative(event.timestamp)}</span>
            </div>
            <p className="mt-1.5 text-sm font-medium text-foreground">
              {event.title}
            </p>
            {event.description && (
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {event.description}
              </p>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}
