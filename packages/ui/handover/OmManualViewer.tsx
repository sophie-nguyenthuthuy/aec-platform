"use client";

import { Wrench, Loader2, CheckCircle2, XCircle } from "lucide-react";
import type { OmManual, OmManualStatus } from "./types";

interface OmManualViewerProps {
  manual: OmManual;
}

const STATUS_LABEL: Record<OmManualStatus, string> = {
  draft: "Bản nháp",
  generating: "Đang sinh",
  ready: "Sẵn sàng",
  failed: "Thất bại",
};

const STATUS_STYLE: Record<OmManualStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  generating: "bg-amber-100 text-amber-800",
  ready: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
};

export function OmManualViewer({ manual }: OmManualViewerProps): JSX.Element {
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Wrench className="text-blue-600" size={20} />
            <h3 className="text-lg font-semibold text-slate-900">
              {manual.title}
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {manual.discipline.toUpperCase()} · Tạo{" "}
            {new Date(manual.generated_at).toLocaleString("vi-VN")}
          </p>
        </div>
        <StatusBadge status={manual.status} />
      </div>

      <section>
        <h4 className="mb-2 text-sm font-semibold text-slate-900">
          Thiết bị ({manual.equipment.length})
        </h4>
        {manual.equipment.length === 0 ? (
          <p className="text-sm text-slate-500">Chưa trích xuất được thiết bị.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Tag</th>
                  <th className="px-3 py-2">Tên</th>
                  <th className="px-3 py-2">Hãng</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2">Vị trí</th>
                  <th className="px-3 py-2">Công suất</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {manual.equipment.map((eq) => (
                  <tr key={eq.tag}>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-700">
                      {eq.tag}
                    </td>
                    <td className="px-3 py-2 text-slate-900">{eq.name}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {eq.manufacturer ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-700">
                      {eq.model ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-700">
                      {eq.location ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-700">
                      {eq.capacity ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h4 className="mb-2 text-sm font-semibold text-slate-900">
          Lịch bảo trì ({manual.maintenance_schedule.length})
        </h4>
        {manual.maintenance_schedule.length === 0 ? (
          <p className="text-sm text-slate-500">Chưa có lịch bảo trì.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Thiết bị</th>
                  <th className="px-3 py-2">Công việc</th>
                  <th className="px-3 py-2">Chu kỳ</th>
                  <th className="px-3 py-2">Thời gian</th>
                  <th className="px-3 py-2">Dụng cụ</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {manual.maintenance_schedule.map((t, i) => (
                  <tr key={`${t.equipment_tag}-${i}`}>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-700">
                      {t.equipment_tag}
                    </td>
                    <td className="px-3 py-2 text-slate-900">{t.task}</td>
                    <td className="px-3 py-2 text-slate-700">{t.frequency}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {t.duration_minutes ? `${t.duration_minutes} phút` : "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-700">
                      {t.tools.length > 0 ? t.tools.join(", ") : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatusBadge({ status }: { status: OmManualStatus }): JSX.Element {
  const Icon =
    status === "ready"
      ? CheckCircle2
      : status === "failed"
        ? XCircle
        : status === "generating"
          ? Loader2
          : null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_STYLE[status]}`}
    >
      {Icon && (
        <Icon
          size={12}
          className={status === "generating" ? "animate-spin" : ""}
        />
      )}
      {STATUS_LABEL[status]}
    </span>
  );
}
