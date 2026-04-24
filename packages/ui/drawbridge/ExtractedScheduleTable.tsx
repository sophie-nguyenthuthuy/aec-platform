"use client";

import { Download } from "lucide-react";

import type { ExtractedSchedule } from "./types";
import { cn } from "../lib/cn";

interface ExtractedScheduleTableProps {
  schedule: ExtractedSchedule;
  onExportCsv?(schedule: ExtractedSchedule): void;
  className?: string;
}

export function ExtractedScheduleTable({
  schedule,
  onExportCsv,
  className,
}: ExtractedScheduleTableProps): JSX.Element {
  return (
    <section className={cn("rounded-xl border border-slate-200 bg-white", className)}>
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{schedule.name}</h3>
          {schedule.page != null && (
            <p className="text-xs text-slate-500">Trang {schedule.page}</p>
          )}
        </div>
        {onExportCsv && (
          <button
            type="button"
            onClick={() => onExportCsv(schedule)}
            className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            <Download size={12} /> CSV
          </button>
        )}
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
            <tr>
              {schedule.columns.map((c) => (
                <th key={c} className="px-3 py-2 text-left font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {schedule.rows.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50">
                {schedule.columns.map((c) => (
                  <td key={c} className="px-3 py-1.5 text-slate-800">
                    {formatCell(r.cells[c])}
                  </td>
                ))}
              </tr>
            ))}
            {schedule.rows.length === 0 && (
              <tr>
                <td colSpan={schedule.columns.length || 1} className="px-3 py-6 text-center text-xs text-slate-400">
                  Không có dữ liệu
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return v.toString();
  return String(v);
}
