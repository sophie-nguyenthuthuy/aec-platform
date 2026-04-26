"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Lock,
  Sparkles,
} from "lucide-react";

import {
  useBaseline,
  useRunRiskAssessment,
  useSchedule,
} from "@/hooks/schedule";
import type { Activity } from "@/hooks/schedule";

const STATUS_BADGE: Record<string, string> = {
  not_started: "bg-slate-100 text-slate-700",
  in_progress: "bg-blue-100 text-blue-700",
  complete: "bg-emerald-100 text-emerald-700",
  on_hold: "bg-yellow-100 text-yellow-700",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

function dayDiff(a: string, b: string): number {
  return Math.round(
    (new Date(a).getTime() - new Date(b).getTime()) / 86_400_000,
  );
}

export default function ScheduleDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data, isLoading, isError } = useSchedule(id);
  const baseline = useBaseline(id ?? "");
  const runRisk = useRunRiskAssessment(id ?? "");

  const criticalSet = useMemo(
    () => new Set(data?.latest_risk_assessment?.critical_path_codes ?? []),
    [data?.latest_risk_assessment],
  );

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (isError || !data) {
    return (
      <div className="space-y-3">
        <Link href="/schedule" className="text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} className="mr-1 inline" /> Quay lại
        </Link>
        <p className="text-sm text-red-600">Không tìm thấy lịch này.</p>
      </div>
    );
  }

  const { schedule, activities, latest_risk_assessment } = data;

  // Cheap Gantt: pin every bar against the project's earliest start.
  const minDate = activities.reduce<string | null>((acc, a) => {
    const d = a.planned_start;
    if (!d) return acc;
    return acc && acc < d ? acc : d;
  }, null);
  const maxDate = activities.reduce<string | null>((acc, a) => {
    const d = a.planned_finish ?? a.actual_finish;
    if (!d) return acc;
    return acc && acc > d ? acc : d;
  }, null);
  const span =
    minDate && maxDate ? Math.max(1, dayDiff(maxDate, minDate) + 1) : 0;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/schedule"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Tất cả lịch
        </Link>
        <div className="mt-2 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{schedule.name}</h2>
            <p className="mt-1 text-sm text-slate-600">
              Trạng thái: <span className="font-medium">{schedule.status}</span>
              {" · "}Data date: {formatDate(schedule.data_date)}
              {schedule.baseline_set_at && (
                <>
                  {" · "}Baseline đã chốt:{" "}
                  {formatDate(schedule.baseline_set_at)}
                </>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            {!schedule.baseline_set_at && (
              <button
                type="button"
                onClick={() => baseline.mutate(undefined)}
                disabled={baseline.isPending || activities.length === 0}
                className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm text-amber-800 hover:bg-amber-100 disabled:opacity-50"
              >
                <Lock size={14} /> {baseline.isPending ? "Đang chốt..." : "Chốt baseline"}
              </button>
            )}
            <button
              type="button"
              onClick={() => runRisk.mutate(true)}
              disabled={runRisk.isPending}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Sparkles size={14} />
              {runRisk.isPending ? "Đang phân tích..." : "Phân tích rủi ro"}
            </button>
          </div>
        </div>
      </div>

      {/* Stats strip */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Số hoạt động" value={schedule.activity_count.toString()} />
        <Stat
          label="Trễ tiến độ"
          value={schedule.behind_schedule_count.toString()}
          tone={schedule.behind_schedule_count > 0 ? "red" : "emerald"}
        />
        <Stat
          label="Trên CPM"
          value={schedule.on_critical_path_count.toString()}
          tone="amber"
        />
        <Stat
          label="Tiến độ tổng"
          value={`${schedule.percent_complete.toFixed(0)}%`}
        />
      </div>

      {/* Risk panel */}
      {latest_risk_assessment ? (
        <RiskPanel assessment={latest_risk_assessment} />
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
          Chưa có phân tích rủi ro. Bấm <strong>Phân tích rủi ro</strong> để
          AI tính CPM và phát hiện hoạt động có nguy cơ trễ.
        </div>
      )}

      {/* Activities — Gantt-ish */}
      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">
          Danh sách hoạt động ({activities.length})
        </div>
        {activities.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Chưa có hoạt động nào trong lịch này.
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {activities.map((a) => (
              <ActivityRow
                key={a.id}
                a={a}
                minDate={minDate}
                span={span}
                isCritical={criticalSet.has(a.code)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: string;
  tone?: "slate" | "red" | "emerald" | "amber";
}) {
  const colors: Record<string, string> = {
    slate: "text-slate-900",
    red: "text-red-700",
    emerald: "text-emerald-700",
    amber: "text-amber-700",
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-base font-semibold ${colors[tone] ?? colors.slate}`}>
        {value}
      </p>
    </div>
  );
}

function RiskPanel({
  assessment,
}: {
  assessment: NonNullable<ReturnType<typeof useSchedule>["data"]>["latest_risk_assessment"] extends infer T ? T : never;
}) {
  if (!assessment) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">
          Phân tích rủi ro AI
        </h3>
        <span className="text-[11px] text-slate-500">
          {new Date(assessment.generated_at).toLocaleString("vi-VN")}
          {assessment.model_version && ` · ${assessment.model_version}`}
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3 text-xs">
        <div className="rounded-md bg-slate-50 px-3 py-2">
          <p className="text-slate-500">Trễ dự kiến trên CPM</p>
          <p className="mt-0.5 text-base font-semibold text-slate-900">
            {assessment.overall_slip_days} ngày
          </p>
        </div>
        <div className="rounded-md bg-slate-50 px-3 py-2">
          <p className="text-slate-500">Critical path</p>
          <p className="mt-0.5 truncate font-mono text-xs text-slate-800">
            {assessment.critical_path_codes.join(" → ") || "—"}
          </p>
        </div>
        <div className="rounded-md bg-slate-50 px-3 py-2">
          <p className="text-slate-500">Mức độ tin cậy</p>
          <p className="mt-0.5 text-base font-semibold text-slate-900">
            {assessment.confidence_pct != null
              ? `${assessment.confidence_pct}%`
              : "—"}
          </p>
        </div>
      </div>

      {assessment.top_risks.length === 0 ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-emerald-700">
          <CheckCircle2 size={14} /> Không phát hiện rủi ro lớn.
          {assessment.notes && <span className="text-slate-600"> · {assessment.notes}</span>}
        </div>
      ) : (
        <ul className="mt-4 space-y-2">
          {assessment.top_risks.map((r, i) => (
            <li
              key={i}
              className="rounded-md border border-rose-100 bg-rose-50 p-3 text-xs"
            >
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-medium text-rose-900">
                  <AlertTriangle size={12} className="mr-1 inline" />
                  {r.code} · {r.name}
                </p>
                <span className="font-mono text-rose-700">
                  +{r.expected_slip_days} ngày
                </span>
              </div>
              <p className="mt-1 text-rose-800">{r.reason}</p>
              <p className="mt-1 italic text-rose-700">→ {r.mitigation}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ActivityRow({
  a,
  minDate,
  span,
  isCritical,
}: {
  a: Activity;
  minDate: string | null;
  span: number;
  isCritical: boolean;
}) {
  const startOffset =
    minDate && a.planned_start ? dayDiff(a.planned_start, minDate) : 0;
  const dur =
    a.planned_start && a.planned_finish
      ? Math.max(1, dayDiff(a.planned_finish, a.planned_start) + 1)
      : 1;
  const leftPct = span > 0 ? (startOffset / span) * 100 : 0;
  const widthPct = span > 0 ? (dur / span) * 100 : 0;

  const slipped =
    a.baseline_finish &&
    a.planned_finish &&
    new Date(a.planned_finish) > new Date(a.baseline_finish);

  return (
    <li className="flex items-center gap-4 px-4 py-2.5 text-xs">
      <div className="w-16 shrink-0 font-mono text-slate-700">{a.code}</div>
      <div className="w-48 shrink-0 truncate">{a.name}</div>
      <span
        className={`w-24 shrink-0 rounded-full px-2 py-0.5 text-center text-[10px] font-medium ${
          STATUS_BADGE[a.status] ?? "bg-slate-100 text-slate-700"
        }`}
      >
        {a.status}
      </span>
      <div className="w-24 shrink-0 text-slate-600">
        {a.percent_complete.toFixed(0)}%
      </div>

      {/* Bar */}
      <div className="relative h-6 flex-1 overflow-hidden rounded bg-slate-50">
        {a.planned_start && a.planned_finish && (
          <div
            title={`${formatDate(a.planned_start)} → ${formatDate(a.planned_finish)}`}
            className={`absolute top-0 h-full rounded ${
              isCritical
                ? "bg-rose-400"
                : slipped
                ? "bg-amber-400"
                : "bg-blue-400"
            }`}
            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
          />
        )}
        {/* Progress overlay */}
        {a.planned_start && a.planned_finish && a.percent_complete > 0 && (
          <div
            className="absolute top-0 h-full rounded bg-blue-700/70"
            style={{
              left: `${leftPct}%`,
              width: `${(widthPct * Math.min(100, a.percent_complete)) / 100}%`,
            }}
          />
        )}
      </div>

      <div className="w-32 shrink-0 text-right text-slate-500">
        {formatDate(a.planned_start)} → {formatDate(a.planned_finish)}
      </div>
    </li>
  );
}
