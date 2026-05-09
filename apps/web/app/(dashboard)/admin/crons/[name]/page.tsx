"use client";

/**
 * Per-cron drilldown — `/admin/crons/[name]`.
 *
 * Lands here from a row click on `/admin/crons`. Shows the recent-runs
 * history for one cron: a status sparkline (each invocation as a
 * coloured bar — green/red/amber for succeeded/failed/running) and a
 * table with timestamps, duration, and the truncated error message
 * on failure rows.
 *
 * Path param `[name]` is the arq cron name (`cron:<func_name>`).
 * `useParams()` returns the URL-decoded form, which `useCronRuns`
 * re-encodes for the API path.
 *
 * Mirrors the H3 (api-usage) + J2 (webhook delivery) drilldowns —
 * same idiom: header + section grid (sparkline / runs table /
 * description) + Link back to the parent. Visual consistency lets
 * ops move between admin surfaces without re-learning the layout.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  CheckCircle2,
  Clock,
  Loader2,
  PlayCircle,
} from "lucide-react";

import {
  type CronRunEntry,
  useCrons,
  useCronRuns,
  useRunCronNow,
} from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


export default function CronDrilldownPage(): JSX.Element {
  const session = useSession();
  const params = useParams();
  // The path param is URL-decoded by Next so `cron%3Aweekly_report_cron`
  // arrives as `cron:weekly_report_cron`. `useCronRuns` re-encodes it
  // for the API call.
  const cronName =
    typeof params?.name === "string" ? params.name : undefined;

  const isAdmin =
    session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  // Pull the registry too so we can show this cron's schedule + next-run
  // alongside the runs history. Cheap (registry query is tiny + cached
  // by the hook's 60s refetch interval shared with the parent page).
  const registry = useCrons();
  const meta = registry.data?.find((c) => c.name === cronName);

  const runs = useCronRuns(cronName);

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
        Quay lại registry
      </Link>

      <header className="space-y-2">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <Clock size={20} className="text-blue-600" />
            <h1 className="font-mono text-xl font-semibold text-slate-900">
              {meta?.function ?? cronName ?? "—"}
            </h1>
          </div>
          {cronName && <RunNowButton cronName={cronName} />}
        </div>
        {meta && (
          <>
            <p className="font-mono text-[11px] text-slate-400">
              {meta.module} · {meta.name}
            </p>
            <p className="text-sm text-slate-700">
              {meta.description || (
                <span className="text-slate-400">— (no docstring)</span>
              )}
            </p>
            <p className="text-xs text-slate-500">
              <span className="font-medium">Schedule:</span> {meta.schedule}
            </p>
          </>
        )}
      </header>

      {runs.isLoading && (
        <p className="text-sm text-slate-500">Đang tải runs...</p>
      )}

      {runs.isError && (
        <ErrorBanner error={runs.error as Error | null} />
      )}

      {runs.data && (
        <>
          {/* ---------- Sparkline ---------- */}
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <header className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Run history
              </h2>
              <p className="text-[11px] text-slate-500">
                {runs.data.length} most recent · oldest left, newest right
              </p>
            </header>
            <RunSparkline runs={runs.data} />
            <RunSparklineLegend />
          </section>

          {/* ---------- Runs table ---------- */}
          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            {runs.data.length === 0 ? (
              <div className="px-4 py-12 text-center text-sm text-slate-500">
                Cron này chưa có run nào trong telemetry. Có thể chưa fire
                kể từ khi telemetry được deploy, hoặc tất cả rows đã được
                retention-prune (30 ngày).
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Started</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2 text-right">Duration</th>
                    <th className="px-4 py-2">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.data.map((run) => (
                    <RunRow key={run.id} run={run} />
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


/**
 * "Run now" button — fires the manual-run endpoint and shows brief
 * feedback while the arq worker picks up the job.
 *
 * Why a confirm() guard: most crons in this codebase have real side
 * effects (S3 writes, downstream HTTP, Slack messages). An accidental
 * click on `daily_activity_digest_cron` would mass-email every user
 * who has watched a project — a friction step is the right tradeoff.
 *
 * Post-success state: the button shows a brief "enqueued" check for
 * a few seconds, then resets. The drilldown's `useCronRuns` hook
 * (30s poll) is the durable feedback — the new `cron_runs` row
 * appears in the sparkline within one tick.
 */
function RunNowButton({ cronName }: { cronName: string }) {
  const runNow = useRunCronNow();
  const [justEnqueued, setJustEnqueued] = useState(false);

  function handleClick() {
    if (
      !confirm(
        `Run cron "${cronName}" right now?\n\nThis fires the same code path as a scheduled tick — it can hit the DB, Slack, S3, and partner endpoints.`,
      )
    ) {
      return;
    }
    runNow.mutate(cronName, {
      onSuccess: () => {
        setJustEnqueued(true);
        setTimeout(() => setJustEnqueued(false), 4000);
      },
    });
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={runNow.isPending || justEnqueued}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
        justEnqueued
          ? "border border-emerald-300 bg-emerald-50 text-emerald-800"
          : "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:opacity-50"
      }`}
      title="Enqueue an arq job that runs this cron now. New cron_runs row appears in the sparkline within ~30s."
    >
      {runNow.isPending ? (
        <>
          <Loader2 size={12} className="animate-spin" />
          Enqueuing...
        </>
      ) : justEnqueued ? (
        <>
          <CheckCircle2 size={12} />
          Enqueued — watch sparkline
        </>
      ) : (
        <>
          <PlayCircle size={12} />
          Run now
        </>
      )}
    </button>
  );
}


/**
 * Status sparkline — one tiny coloured bar per run, oldest-left to
 * newest-right (so the natural reading order matches "what just
 * happened most recently is on the right"). Reverses the API's
 * newest-first ordering specifically for visual scan.
 *
 * Each bar is 12px wide; up to 20 bars total at the API cap. Hover
 * shows the absolute timestamp + duration in the title attribute.
 */
function RunSparkline({ runs }: { runs: CronRunEntry[] }) {
  // API returns newest-first; reverse for visual oldest-→-newest.
  const ordered = [...runs].reverse();
  return (
    <div className="mt-3 flex items-end gap-0.5">
      {ordered.map((run) => {
        const tone = colourForStatus(run.status);
        // Bar height is fixed (sparkline is status-coloured, not
        // duration-scaled — duration goes on the table row). Height
        // varies SLIGHTLY by status so failures stick up: green and
        // amber both 16px, red 22px to draw the eye.
        const height = run.status === "failed" ? "h-6" : "h-4";
        const ts = run.started_at ? new Date(run.started_at) : null;
        const tooltip = [
          run.status,
          ts ? ts.toLocaleString("vi-VN") : null,
          run.duration_ms !== null ? `${run.duration_ms}ms` : null,
          run.error_message,
        ]
          .filter(Boolean)
          .join("\n");
        return (
          <span
            key={run.id}
            className={`w-3 rounded-sm ${height} ${tone}`}
            title={tooltip}
            aria-label={tooltip}
          />
        );
      })}
    </div>
  );
}


function RunSparklineLegend() {
  return (
    <div className="mt-3 flex items-center gap-4 text-[11px] text-slate-500">
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500" />
        succeeded
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block h-2 w-2 rounded-sm bg-rose-500" />
        failed
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block h-2 w-2 rounded-sm bg-amber-500" />
        running
      </span>
    </div>
  );
}


function RunRow({ run }: { run: CronRunEntry }) {
  const ts = run.started_at ? new Date(run.started_at) : null;
  return (
    <tr className="align-top">
      <td className="px-4 py-2 text-xs text-slate-700">
        {ts ? (
          <>
            <p>{ts.toLocaleString("vi-VN")}</p>
            <p className="mt-0.5 text-[10px] text-slate-400">
              {formatRelativePast(ts)}
            </p>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="px-4 py-2">
        <StatusPill status={run.status} />
      </td>
      <td className="px-4 py-2 text-right font-mono text-xs text-slate-700">
        {run.duration_ms !== null ? formatDuration(run.duration_ms) : "—"}
      </td>
      <td className="px-4 py-2">
        {run.error_message ? (
          <p
            className="line-clamp-2 max-w-md font-mono text-[10px] text-rose-700"
            title={run.error_message}
          >
            {run.error_message}
          </p>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
    </tr>
  );
}


function StatusPill({ status }: { status: string }) {
  const tone = colourForStatusPill(status);
  return (
    <span
      className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}
    >
      {status}
    </span>
  );
}


function ErrorBanner({ error }: { error: Error | null }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <p>
        Không thể tải lịch sử runs:{" "}
        {error?.message ?? "lỗi không xác định"}
      </p>
    </div>
  );
}


// ---------- Pure helpers ----------


/** Sparkline-bar background colour. Distinct from the pill palette so
 *  the bars read as "pure status indicators" while the pills carry
 *  the readable label. */
function colourForStatus(status: string): string {
  if (status === "succeeded") return "bg-emerald-500";
  if (status === "failed") return "bg-rose-500";
  if (status === "running") return "bg-amber-500";
  return "bg-slate-300"; // unknown/future status
}


function colourForStatusPill(status: string): string {
  if (status === "succeeded") return "bg-emerald-100 text-emerald-800";
  if (status === "failed") return "bg-rose-100 text-rose-800";
  if (status === "running") return "bg-amber-100 text-amber-800";
  return "bg-slate-200 text-slate-800";
}


function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
}


function formatRelativePast(d: Date): string {
  const ms = Date.now() - d.getTime();
  if (ms < 0) return "just now";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.round(hr / 24);
  return `${days}d ago`;
}
