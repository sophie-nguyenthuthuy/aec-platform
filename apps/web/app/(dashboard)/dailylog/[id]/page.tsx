"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CloudRain,
  HardHat,
  Sparkles,
  Wrench,
} from "lucide-react";

import { useDailyLog, useTriggerExtract } from "@/hooks/dailylog";
import type { Observation } from "@/hooks/dailylog";

const SEVERITY_BADGE: Record<string, string> = {
  low: "bg-slate-100 text-slate-700",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-orange-100 text-orange-800",
  critical: "bg-red-100 text-red-800",
};

const STATUS_BADGE: Record<string, string> = {
  open: "bg-amber-100 text-amber-800",
  in_progress: "bg-blue-100 text-blue-800",
  resolved: "bg-emerald-100 text-emerald-800",
  dismissed: "bg-slate-100 text-slate-600",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function DailyLogDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data, isLoading, isError } = useDailyLog(id);
  const extract = useTriggerExtract(id ?? "");

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (isError || !data) {
    return (
      <div className="space-y-3">
        <Link href="/dailylog" className="text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} className="mr-1 inline" /> Quay lại
        </Link>
        <p className="text-sm text-red-600">Không tìm thấy nhật ký.</p>
      </div>
    );
  }

  const { summary, weather, narrative, manpower, equipment, observations } = data;
  const totalHeadcount = manpower.reduce((s, m) => s + m.headcount, 0);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/dailylog"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Tất cả nhật ký
        </Link>
        <div className="mt-2 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              Nhật ký {formatDate(summary.log_date)}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Trạng thái: <span className="font-medium">{summary.status}</span>
              {summary.submitted_at && ` · Nộp: ${formatDate(summary.submitted_at)}`}
              {summary.approved_at && ` · Duyệt: ${formatDate(summary.approved_at)}`}
            </p>
          </div>
          <button
            type="button"
            onClick={() => extract.mutate(true)}
            disabled={extract.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Sparkles size={14} />
            {extract.isPending ? "Đang phân tích..." : "Trích xuất lại bằng AI"}
          </button>
        </div>
      </div>

      {/* Weather + headcount strip */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-500">
            <CloudRain size={12} /> Thời tiết
          </div>
          <p className="mt-1 text-sm text-slate-800">
            {(weather.conditions as string) || "—"}
            {weather.temp_c != null && ` · ${weather.temp_c}°C`}
            {weather.precipitation_mm != null &&
              Number(weather.precipitation_mm) > 0 &&
              ` · ${weather.precipitation_mm}mm`}
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-500">
            <HardHat size={12} /> Nhân lực
          </div>
          <p className="mt-1 text-base font-semibold text-slate-900">
            {totalHeadcount} người · {manpower.length} tổ
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-500">
            <Wrench size={12} /> Thiết bị
          </div>
          <p className="mt-1 text-base font-semibold text-slate-900">
            {equipment.length} loại
          </p>
        </div>
      </div>

      {narrative && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Mô tả công việc</h3>
          <p className="whitespace-pre-wrap text-sm text-slate-700">{narrative}</p>
        </div>
      )}

      {/* Observations */}
      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-baseline justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Vấn đề / rủi ro ghi nhận ({observations.length})
          </h3>
          <span className="text-[11px] text-slate-500">
            {observations.filter((o) => o.source === "llm_extracted").length} do AI · {" "}
            {observations.filter((o) => o.source === "manual").length} thủ công · {" "}
            {observations.filter((o) => o.source === "siteeye_hit").length} từ SiteEye
          </span>
        </div>
        {observations.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">Chưa có quan sát nào.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {observations.map((o) => (
              <ObservationRow key={o.id} obs={o} />
            ))}
          </ul>
        )}
      </div>

      {/* Manpower & equipment */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">
            Nhân lực
          </div>
          {manpower.length === 0 ? (
            <p className="p-4 text-sm text-slate-500">Chưa có dữ liệu.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {manpower.map((m, i) => (
                <li key={m.id ?? i} className="flex justify-between px-4 py-2">
                  <span>{m.trade}</span>
                  <span className="font-medium text-slate-900">
                    {m.headcount} người
                    {m.hours_worked != null && ` · ${m.hours_worked}h`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">
            Thiết bị
          </div>
          {equipment.length === 0 ? (
            <p className="p-4 text-sm text-slate-500">Chưa có dữ liệu.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {equipment.map((e, i) => (
                <li key={e.id ?? i} className="flex justify-between px-4 py-2">
                  <span>
                    {e.name} ×{e.quantity}
                  </span>
                  <span className="font-medium text-slate-900">
                    {e.state}
                    {e.hours_used != null && ` · ${e.hours_used}h`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function ObservationRow({ obs }: { obs: Observation }) {
  return (
    <li className="px-4 py-3 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-2">
          <AlertTriangle size={12} className="text-amber-600" />
          <span className="font-medium text-slate-900">{obs.kind}</span>
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
              SEVERITY_BADGE[obs.severity] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {obs.severity}
          </span>
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
              STATUS_BADGE[obs.status] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {obs.status}
          </span>
          {obs.source === "llm_extracted" && (
            <span className="text-[10px] text-blue-600">AI</span>
          )}
          {obs.source === "siteeye_hit" && (
            <span className="text-[10px] text-purple-600">SiteEye</span>
          )}
        </div>
      </div>
      <p className="mt-1 text-slate-700">{obs.description}</p>
    </li>
  );
}
