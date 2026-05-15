"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Clock,
  Layers,
  Loader2,
  RefreshCcw,
  XCircle,
  Zap,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Background job dashboard. Surfaces arq queue state for the ops
 * team's "is anything wedged?" check.
 *
 * Three sections:
 *   1. KPI tiles — queued / in_progress / complete (1h) / failed (1h).
 *   2. Cron schedule — when each cron next runs.
 *   3. Recent jobs — filterable list of completed/failed with
 *      function name, runtime, last_failure preview.
 *
 * Admin-gated server-side; the page surfaces a friendly 403 message
 * if a non-admin lands here via shared URL.
 */

interface JobsSummary {
  queued: number;
  in_progress: number;
  complete_last_hour: number;
  failed_last_hour: number;
}

interface JobRow {
  function: string;
  job_id: string;
  success: boolean;
  queue_name: string | null;
  enqueue_time_ms: number | null;
  start_time_ms: number | null;
  finish_time_ms: number | null;
  runtime_ms: number | null;
  last_failure: string | null;
}

interface CronEntry {
  function: string;
  hour: unknown;
  minute: unknown;
  weekday: unknown;
  day: unknown;
  month: unknown;
}


type FilterMode = "all" | "complete" | "failed";


export default function AdminJobsPage() {
  const { token, orgId } = useSession();
  const [summary, setSummary] = useState<JobsSummary | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [crons, setCrons] = useState<CronEntry[]>([]);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  // ---- Data load ----
  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        // Build the recent-jobs path with concat instead of a template
        // literal so the static apiFetch-path linter (which can't eval
        // `${onlyParam}`) sees a stable string for route matching.
        const recentPath =
          filter !== "all"
            ? "/api/v1/admin/jobs/recent?only=" + filter
            : "/api/v1/admin/jobs/recent";
        const [s, j, c] = await Promise.all([
          apiFetch<JobsSummary>("/api/v1/admin/jobs/summary", { token, orgId }),
          apiFetch<{ jobs: JobRow[] }>(recentPath, { token, orgId }),
          apiFetch<{ crons: CronEntry[] }>("/api/v1/admin/jobs/cron", { token, orgId }),
        ]);
        if (cancelled) return;
        setSummary(s.data!);
        setJobs(j.data!.jobs);
        setCrons(c.data!.crons);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, orgId, filter, refreshTick]);

  // ---- Auto-refresh summary every 15s (cheap) ----
  useEffect(() => {
    const id = setInterval(() => setRefreshTick((t) => t + 1), 15_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Hàng đợi job nền</h2>
          <p className="text-sm text-slate-600">
            Trạng thái arq worker — drawbridge ingest, weekly report,
            CostPulse price-alert, SiteEye photo analysis, RFQ dispatch.
            Tự động làm mới mỗi 15 giây.
          </p>
        </div>
        <button
          onClick={() => setRefreshTick((t) => t + 1)}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          <RefreshCcw size={14} />
          Làm mới ngay
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <AlertCircle size={14} className="mr-1 inline" />
          {error}
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiTile
          icon={<Layers size={14} />}
          label="Đang chờ"
          value={summary?.queued}
          loading={loading}
          tone="default"
        />
        <KpiTile
          icon={<Zap size={14} />}
          label="Đang chạy"
          value={summary?.in_progress}
          loading={loading}
          tone="blue"
        />
        <KpiTile
          icon={<CheckCircle2 size={14} />}
          label="Hoàn thành (1h)"
          value={summary?.complete_last_hour}
          loading={loading}
          tone="emerald"
        />
        <KpiTile
          icon={<XCircle size={14} />}
          label="Lỗi (1h)"
          value={summary?.failed_last_hour}
          loading={loading}
          tone="rose"
        />
      </div>

      {/* Cron schedule */}
      <section className="rounded-xl border border-slate-200 bg-white">
        <header className="border-b border-slate-200 px-4 py-2.5">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <Calendar size={14} />
            Lịch định kỳ ({crons.length})
          </h3>
        </header>
        {crons.length === 0 ? (
          <p className="px-4 py-3 text-sm text-slate-500">Không có cron nào.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {crons.map((c) => (
              <li key={c.function} className="flex items-center gap-3 px-4 py-2 text-sm">
                <code className="font-mono text-xs text-slate-700">{c.function}</code>
                <span className="text-xs text-slate-500">
                  {describeCron(c)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Recent jobs */}
      <section className="rounded-xl border border-slate-200 bg-white">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5">
          <h3 className="text-sm font-semibold text-slate-900">
            Job gần đây ({jobs.length})
          </h3>
          <div className="inline-flex rounded-md bg-slate-100 p-0.5 text-xs">
            <FilterTab active={filter === "all"} onClick={() => setFilter("all")} label="Tất cả" />
            <FilterTab active={filter === "complete"} onClick={() => setFilter("complete")} label="Thành công" />
            <FilterTab active={filter === "failed"} onClick={() => setFilter("failed")} label="Lỗi" />
          </div>
        </header>
        {loading && jobs.length === 0 ? (
          <p className="px-4 py-6 text-sm text-slate-500">
            <Loader2 size={14} className="mr-1 inline animate-spin" /> Đang tải…
          </p>
        ) : jobs.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-slate-500">
            Chưa có job nào khớp lọc.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {jobs.map((j) => (
              <JobRowItem key={j.job_id} job={j} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}


function KpiTile({
  icon,
  label,
  value,
  loading,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | undefined;
  loading: boolean;
  tone: "default" | "blue" | "emerald" | "rose";
}) {
  const valueTone = {
    default: "text-slate-900",
    blue: "text-blue-700",
    emerald: "text-emerald-700",
    rose: "text-rose-700",
  }[tone];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-1 text-2xl font-semibold ${valueTone}`}>
        {loading && value === undefined ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          (value ?? 0).toLocaleString("vi-VN")
        )}
      </p>
    </div>
  );
}


function FilterTab({
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
      onClick={onClick}
      className={`rounded px-3 py-1 ${
        active
          ? "bg-white font-medium text-slate-900 shadow-sm"
          : "text-slate-500 hover:text-slate-700"
      }`}
    >
      {label}
    </button>
  );
}


function JobRowItem({ job }: { job: JobRow }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="px-4 py-2.5">
      <div
        className="flex cursor-pointer items-start gap-3"
        onClick={() => job.last_failure && setExpanded((v) => !v)}
      >
        {job.success ? (
          <CheckCircle2 size={14} className="mt-0.5 flex-shrink-0 text-emerald-500" />
        ) : (
          <XCircle size={14} className="mt-0.5 flex-shrink-0 text-rose-500" />
        )}
        <div className="flex-1 min-w-0">
          <p className="font-mono text-xs text-slate-900">{job.function}</p>
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
            <span className="font-mono">id:{job.job_id.slice(0, 12)}</span>
            {job.runtime_ms !== null && (
              <span>
                <Clock size={10} className="mr-1 inline" />
                {formatRuntime(job.runtime_ms)}
              </span>
            )}
            {job.finish_time_ms && (
              <span>
                hoàn tất {formatVnDateTime(job.finish_time_ms)}
              </span>
            )}
          </div>
        </div>
      </div>
      {job.last_failure && expanded && (
        <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-rose-50 px-3 py-2 text-[11px] text-rose-800">
          {job.last_failure}
        </pre>
      )}
      {job.last_failure && !expanded && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
          className="mt-1 ml-7 text-[11px] text-rose-700 underline hover:no-underline"
        >
          Xem lỗi
        </button>
      )}
    </li>
  );
}


function describeCron(c: CronEntry): string {
  // Format the cron fields in human-friendly Vietnamese.
  // Each field is one of: null (any), int, or array of ints.
  const parts: string[] = [];
  if (c.weekday !== null && c.weekday !== undefined) {
    parts.push(`thứ ${formatField(c.weekday)}`);
  }
  if (c.day !== null && c.day !== undefined) {
    parts.push(`ngày ${formatField(c.day)}`);
  }
  if (c.month !== null && c.month !== undefined) {
    parts.push(`tháng ${formatField(c.month)}`);
  }
  if (c.hour !== null && c.hour !== undefined) {
    const m = c.minute !== null && c.minute !== undefined ? formatField(c.minute) : "0";
    parts.push(`${formatField(c.hour)}:${pad(m)} UTC`);
  } else if (c.minute !== null && c.minute !== undefined) {
    const m = c.minute as number | number[];
    if (Array.isArray(m) && m.length >= 60) {
      parts.push("mỗi phút");
    } else {
      parts.push(`phút ${formatField(c.minute)}`);
    }
  }
  return parts.length > 0 ? parts.join(", ") : "luôn";
}


function formatField(v: unknown): string {
  if (Array.isArray(v)) {
    if (v.length >= 30) return "bất kỳ";
    return v.join(",");
  }
  return String(v);
}


function pad(s: string): string {
  if (s.length === 1) return `0${s}`;
  return s;
}


function formatRuntime(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)} phút`;
}


function formatVnDateTime(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} ${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}
