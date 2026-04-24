"use client";

import { MapPin, Camera, User } from "lucide-react";
import type { Defect, DefectPriority, DefectStatus } from "./types";

interface DefectCardProps {
  defect: Defect;
  onStatusChange?: (status: DefectStatus) => void;
  onOpen?: (defect: Defect) => void;
}

const STATUS_LABEL: Record<DefectStatus, string> = {
  open: "Mới",
  assigned: "Đã giao",
  in_progress: "Đang xử lý",
  resolved: "Đã sửa",
  rejected: "Bác bỏ",
};

const STATUS_STYLE: Record<DefectStatus, string> = {
  open: "bg-red-100 text-red-800",
  assigned: "bg-amber-100 text-amber-800",
  in_progress: "bg-blue-100 text-blue-800",
  resolved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-slate-200 text-slate-700",
};

const PRIORITY_LABEL: Record<DefectPriority, string> = {
  low: "Thấp",
  medium: "Trung bình",
  high: "Cao",
  critical: "Khẩn cấp",
};

const PRIORITY_STYLE: Record<DefectPriority, string> = {
  low: "border-slate-300 text-slate-600",
  medium: "border-slate-400 text-slate-700",
  high: "border-orange-400 text-orange-700",
  critical: "border-red-500 text-red-700 bg-red-50",
};

export function DefectCard({
  defect,
  onStatusChange,
  onOpen,
}: DefectCardProps): JSX.Element {
  const locationLabel = formatLocation(defect.location);

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white p-4 transition hover:border-blue-400"
      onClick={onOpen ? () => onOpen(defect) : undefined}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded border px-1.5 py-0.5 text-xs font-medium ${PRIORITY_STYLE[defect.priority]}`}
            >
              {PRIORITY_LABEL[defect.priority]}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[defect.status]}`}
            >
              {STATUS_LABEL[defect.status]}
            </span>
          </div>
          <h4 className="mt-1.5 font-medium text-slate-900">{defect.title}</h4>
          {defect.description && (
            <p className="mt-1 line-clamp-2 text-sm text-slate-600">
              {defect.description}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
            {locationLabel && (
              <span className="inline-flex items-center gap-1">
                <MapPin size={12} />
                {locationLabel}
              </span>
            )}
            {defect.photo_file_ids.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Camera size={12} />
                {defect.photo_file_ids.length} ảnh
              </span>
            )}
            {defect.assignee_id && (
              <span className="inline-flex items-center gap-1">
                <User size={12} />
                Đã giao
              </span>
            )}
            <span>
              Báo cáo {new Date(defect.reported_at).toLocaleDateString("vi-VN")}
            </span>
          </div>
        </div>
        {onStatusChange && (
          <select
            value={defect.status}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) =>
              onStatusChange(e.target.value as DefectStatus)
            }
            className="rounded border border-slate-300 px-2 py-1 text-xs"
          >
            {(Object.keys(STATUS_LABEL) as DefectStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}

function formatLocation(loc: Defect["location"]): string | null {
  if (!loc) return null;
  const room = typeof loc.room === "string" ? loc.room : null;
  const floor = typeof loc.floor === "string" ? loc.floor : null;
  if (room) return room;
  if (floor) return floor;
  return null;
}
