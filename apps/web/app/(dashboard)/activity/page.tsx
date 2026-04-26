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
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Hoạt động</h2>
        <p className="text-sm text-slate-600">
          Dòng sự kiện theo thời gian thực qua tất cả các module — change
          order, task hoàn thành, sự cố an toàn, lỗi tồn đọng, RFI...
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1.5">
          {MODULE_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setModuleFilter(f.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                moduleFilter === f.value
                  ? "bg-blue-600 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-300">·</span>
        <div className="flex flex-wrap gap-1.5">
          {WINDOW_OPTIONS.map((w) => (
            <button
              key={w.value}
              type="button"
              onClick={() => setWindowDays(w.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                windowDays === w.value
                  ? "bg-slate-900 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <p className="text-sm text-red-600">Không thể tải dòng hoạt động.</p>
      ) : events.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <ClipboardList
            size={32}
            className="mx-auto mb-3 text-slate-400"
            aria-hidden
          />
          <p className="text-sm text-slate-500">
            Không có hoạt động nào trong khoảng thời gian này.
          </p>
        </div>
      ) : (
        <ol className="relative space-y-4 border-l border-slate-200 pl-6">
          {events.map((e) => (
            <ActivityRow key={`${e.module}-${e.id}`} event={e} />
          ))}
        </ol>
      )}

      {data?.meta?.total != null && events.length > 0 && (
        <p className="text-xs text-slate-500">
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
      <div className="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
              <span
                className={`rounded-full px-2 py-0.5 font-medium uppercase tracking-wide ${visuals.badgeClass}`}
              >
                {event.module}
              </span>
              <span className="text-slate-400">·</span>
              <span>{EVENT_LABEL[event.event_type]}</span>
              {event.project_id && event.project_name && (
                <>
                  <span className="text-slate-400">·</span>
                  <Link
                    href={`/projects/${event.project_id}` as Route}
                    className="text-blue-600 hover:underline"
                  >
                    {event.project_name}
                  </Link>
                </>
              )}
              <span className="text-slate-400">·</span>
              <span>{formatRelative(event.timestamp)}</span>
            </div>
            <p className="mt-1.5 text-sm font-medium text-slate-900">
              {event.title}
            </p>
            {event.description && (
              <p className="mt-1 line-clamp-2 text-xs text-slate-600">
                {event.description}
              </p>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}
