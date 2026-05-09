"use client";

/**
 * Per-cron drilldown — `/admin/crons/[cron_name]`.
 *
 * Lands here from a row click on `/admin/crons`. Shows the recent
 * invocations of one cron — what ops opens to answer "did the cron
 * just retry?", "is it running long?", "what error did the last
 * failure throw?".
 *
 * Backend reads from `cron_runs` (see `migration 0042_cron_runs.py`
 * + `services/cron_telemetry.py::recent_runs_for_cron`); capped at
 * 20 rows per call. We don't paginate beyond that — for older
 * runs, query the DB directly.
 *
 * What's NOT here (deliberate v1):
 *
 *   * Per-attempt log streaming. Worker logs are in stdout, not in
 *     `cron_runs`; ops chases tracebacks via the worker container's
 *     logs (`error_message` here is the truncated first line, just
 *     enough to answer "what kind of failure?").
 *
 *   * Manual re-fire button. Same blocker as the list page — needs
 *     a cross-tenant queue-enqueue + audit logging. Workaround
 *     today: shell into the worker.
 *
 *   * Sparkline / histogram. The 20-run table is enough density
 *     for ops triage; richer viz can come if "I scrolled the table
 *     looking for failures" becomes a common complaint.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft, AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { type CronRunEntry, useCronRuns } from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


export default function CronDrilldownPage(): JSX.Element {
  const session = useSession();
  const params = useParams();
  // Next.js wraps the dynamic segment value in an array on edge cases
  // (catch-all routes); for `[cron_name]` it's always a string, but
  // we narrow defensively so the type matches `useCronRuns`.
  const cronName =
    typeof params?.cron_name === "string"
      ? decodeURIComponent(params.cron_name)
      : undefined;

  const isAdmin =
    session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const { data, isLoading, isError, error } = useCronRuns(cronName);

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Trang này chỉ dành cho admin nền tảng.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <Link
        href="/admin/crons"
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
      >
        <ChevronLeft size={14} />
        Quay lại danh sách
      </Link>

      <header className="space-y-1">
        <h1 className="font-mono text-xl font-semibold text-slate-900">
          {cronName ?? "—"}
        </h1>
        <p className="text-sm text-slate-500">
          20 lần chạy gần nhất, sắp xếp mới nhất trước. Telemetry được ghi
          bởi <code className="rounded bg-slate-100 px-1 text-[11px]">
            services.cron_telemetry.cron_telemetry_wrap
          </code>
          ; mỗi lần chạy = 1 row trong <code>cron_runs</code>.
        </p>
      </header>

      {isLoading && <p className="text-sm text-slate-500">Đang tải...</p>}

      {isError && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <p>
            Không thể tải lịch sử cron:{" "}
            {(error as Error)?.message ?? "lỗi không xác định"}
          </p>
        </div>
      )}

      {data && data.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-500">
          Cron này chưa có lần chạy nào trong cron_runs. Có thể:
          <ul className="mt-2 list-disc text-left text-xs text-slate-500 marker:text-slate-300 mx-auto inline-block">
            <li>
              Cron mới được đăng ký, chưa đến thời điểm fire đầu tiên.
            </li>
            <li>
              Wrapper{" "}
              <code className="text-[11px]">cron_telemetry_wrap</code> chưa
              được áp dụng cho cron này (xem{" "}
              <code className="text-[11px]">workers/queue.py</code>).
            </li>
            <li>
              Telemetry rows đã bị retention prune (hiện chưa có job prune).
            </li>
          </ul>
        </div>
      )}

      {data && data.length > 0 && (
        <RunsTable runs={data} />
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function RunsTable({ runs }: { runs: CronRunEntry[] }): JSX.Element {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2">Started</th>
            <th className="px-4 py-2">Duration</th>
            <th className="px-4 py-2">Error</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </tbody>
      </table>
    </section>
  );
}


function RunRow({ run }: { run: CronRunEntry }): JSX.Element {
  return (
    <tr className="align-top">
      <td className="px-4 py-3">
        <StatusPill status={run.status} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-slate-700">
        {run.started_at
          ? new Date(run.started_at).toLocaleString("vi-VN")
          : "—"}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-slate-700">
        {formatDuration(run)}
      </td>
      <td className="px-4 py-3 text-xs text-rose-700">
        {run.error_message ? (
          <span className="line-clamp-3 max-w-md font-mono text-[11px]">
            {run.error_message}
          </span>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
    </tr>
  );
}


function StatusPill({ status }: { status: string }) {
  // Tone matches the closed vocabulary in
  // `services/cron_telemetry.py::CronRunStatus`. Unknown statuses
  // fall through to the slate (default) tone — so a future status
  // value renders neutrally rather than as a green/red surprise.
  const config = {
    succeeded: {
      tone: "bg-emerald-100 text-emerald-800",
      Icon: CheckCircle2,
    },
    failed: {
      tone: "bg-rose-100 text-rose-800",
      Icon: AlertCircle,
    },
    running: {
      tone: "bg-blue-100 text-blue-800",
      Icon: Loader2,
    },
  }[status] ?? { tone: "bg-slate-100 text-slate-700", Icon: AlertCircle };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${config.tone}`}
    >
      <config.Icon
        size={11}
        // Spin while the cron is mid-run — gives the page a "live"
        // feel without a true tail-poll.
        className={status === "running" ? "animate-spin" : ""}
      />
      {status}
    </span>
  );
}


function formatDuration(run: CronRunEntry): string {
  if (run.duration_ms === null) {
    // Still running — render a placeholder rather than 0ms.
    if (run.status === "running") return "running…";
    return "—";
  }
  if (run.duration_ms < 1000) return `${run.duration_ms}ms`;
  if (run.duration_ms < 60_000) return `${(run.duration_ms / 1000).toFixed(1)}s`;
  const min = Math.floor(run.duration_ms / 60_000);
  const sec = Math.round((run.duration_ms % 60_000) / 1000);
  return `${min}m ${sec}s`;
}
