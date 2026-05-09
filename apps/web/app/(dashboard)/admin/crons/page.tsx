"use client";

/**
 * Admin dashboard for the arq cron-job registry — `/admin/crons`.
 *
 * Reads from `GET /api/v1/admin/crons` (in-process read of
 * `WorkerSettings.cron_jobs` on the worker module). Lists every
 * registered cron with its schedule, function, and next-due fire time.
 *
 * What this page DOES NOT show in v1:
 *
 *   * Last-run telemetry. arq stores recent JobResult records in
 *     Redis with a short TTL; surfacing "last run" reliably needs a
 *     persisted `cron_runs` audit table or a Redis read with a
 *     "anything older than 1h is gone" caveat. Both are follow-up
 *     work — the static registry is valuable on its own (it's the
 *     source of truth for what a deployed worker should be running).
 *
 *   * Run-now button. Triggering a cron manually from the UI would
 *     need a cross-tenant queue.enqueue path AND audit logging. Out
 *     of scope for v1; ops can manually fire via the existing
 *     `pnpm --filter @aec/api -- python -m workers.queue ...` CLI.
 *
 * Refetches every 60s so `next_run` countdowns stay roughly accurate
 * — the registry itself doesn't change between deploys, but the
 * countdown moves minute-by-minute.
 */

import Link from "next/link";
import { Clock, AlertCircle } from "lucide-react";

import { type CronEntry, useCrons } from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


export default function CronsAdminPage(): JSX.Element {
  const session = useSession();
  const isAdmin =
    session.orgs.find((o) => o.id === session.orgId)?.role === "admin";
  const { data, isLoading, isError, error } = useCrons();

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
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Cron jobs</h1>
          <p className="text-sm text-slate-500">
            Registry cron đang đăng ký trên worker hiện tại. Đọc trực tiếp từ{" "}
            <code className="rounded bg-slate-100 px-1 text-[11px]">
              WorkerSettings.cron_jobs
            </code>
            ; refetch mỗi 60s để countdown <em>next run</em> chính xác.
          </p>
        </div>
        <CountSummary count={data?.length ?? 0} />
      </header>

      {/* Telemetry now wired via `services.cron_telemetry` — every
          cron writes a `cron_runs` row at start + finish. The "no
          telemetry" caveat that lived here in v1 is gone; failures
          surface inline in the table. Retention prunes runs at 30d,
          so a quiet cron may show "no recent runs" even after firing
          historically — that's by design. */}

      {isLoading && <p className="text-sm text-slate-500">Đang tải...</p>}

      {isError && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <p>
            Không thể tải registry:{" "}
            {(error as Error)?.message ?? "lỗi không xác định"}
          </p>
        </div>
      )}

      {data && data.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-500">
          Worker không đăng ký cron nào. Kiểm tra{" "}
          <code className="rounded bg-slate-100 px-1 text-xs">
            apps/api/workers/queue.py::WorkerSettings.cron_jobs
          </code>
          .
        </div>
      )}

      {data && data.length > 0 && (
        // overflow-x-auto so the 5-column table scrolls horizontally
        // on mobile within its rounded-card wrapper rather than the
        // whole viewport. Same idiom as `/admin/api-usage`.
        <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Function</th>
                <th className="px-4 py-2">Schedule</th>
                <th className="px-4 py-2">Last run</th>
                <th className="px-4 py-2">Next run</th>
                <th className="px-4 py-2">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((c) => (
                <CronRow key={c.name} entry={c} />
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function CountSummary({ count }: { count: number }) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-slate-100 px-3 py-1.5 text-xs text-slate-700">
      <Clock size={14} aria-hidden />
      <span>
        <span className="font-semibold">{count}</span>{" "}
        {count === 1 ? "cron đăng ký" : "crons đăng ký"}
      </span>
    </div>
  );
}


function CronRow({ entry }: { entry: CronEntry }) {
  const due = entry.next_run ? new Date(entry.next_run) : null;
  const dueLabel = due ? formatRelativeFuture(due) : "—";
  const dueAbsolute = due ? due.toLocaleString("vi-VN") : "";

  // Drilldown link wraps the function name. The href passes the
  // arq cron name (`cron:<func_name>`) URL-encoded so the colon
  // doesn't trip stricter URL parsers — the drilldown decodes it
  // before passing to the hook.
  const drilldownHref = `/admin/crons/${encodeURIComponent(entry.name)}`;

  return (
    <tr className="align-top">
      <td className="px-4 py-3">
        <Link
          href={drilldownHref}
          className="font-mono text-xs font-semibold text-slate-900 hover:text-blue-700 hover:underline"
        >
          {entry.function}
        </Link>
        <p className="mt-0.5 font-mono text-[10px] text-slate-400">
          {entry.module}
        </p>
      </td>
      <td className="px-4 py-3 text-xs text-slate-700">{entry.schedule}</td>
      <td className="px-4 py-3 text-xs">
        <LastRunCell run={entry.last_run} />
      </td>
      <td className="px-4 py-3 text-xs">
        <p className="font-mono text-slate-900" title={dueAbsolute}>
          {dueLabel}
        </p>
        {due && (
          <p className="mt-0.5 text-[10px] text-slate-500">{dueAbsolute}</p>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-slate-600">
        {entry.description || (
          <span className="text-slate-400">— (no docstring)</span>
        )}
      </td>
    </tr>
  );
}


/**
 * "Last run" cell — three states:
 *
 *   * `null` last_run → "no runs yet" greyed out. The cron is
 *     registered but hasn't fired since telemetry was deployed (or
 *     all rows pruned by 30d retention).
 *
 *   * status="running" + finished_at=null → orange "running" pill +
 *     elapsed seconds. Catches stuck crons; webhook_drain
 *     legitimately runs <1s, so anything >5min is a flag.
 *
 *   * status="succeeded" / "failed" → coloured pill + duration in ms
 *     + relative-past timestamp. Failed cron also shows the truncated
 *     error message in red beneath.
 */
function LastRunCell({ run }: { run: CronEntry["last_run"] }) {
  if (!run) {
    return <span className="text-slate-400">no runs yet</span>;
  }
  const ts = run.started_at ? new Date(run.started_at) : null;
  // STUCK = running AND elapsed > 3× p95. Render in rose like a
  // failure (it IS a failure-mode the watchdog Slack-alerts on);
  // separate label so ops can tell "running normally" from
  // "running too long". Plain `running` stays amber as before.
  const isStuck = run.status === "running" && run.stuck === true;
  const tone = isStuck
    ? "bg-rose-100 text-rose-800"
    : run.status === "succeeded"
      ? "bg-emerald-100 text-emerald-800"
      : run.status === "failed"
        ? "bg-rose-100 text-rose-800"
        : "bg-amber-100 text-amber-800"; // running (not stuck)
  const label = isStuck ? "stuck" : run.status;
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-2">
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}
        >
          {label}
        </span>
        {run.duration_ms !== null && (
          <span className="font-mono text-[11px] text-slate-700">
            {formatDuration(run.duration_ms)}
          </span>
        )}
      </div>
      {ts && (
        <p
          className="text-[10px] text-slate-500"
          title={ts.toLocaleString("vi-VN")}
        >
          {formatRelativePast(ts)}
        </p>
      )}
      {run.status === "failed" && run.error_message && (
        <p
          className="line-clamp-2 max-w-xs font-mono text-[10px] text-rose-700"
          title={run.error_message}
        >
          {run.error_message}
        </p>
      )}
      {isStuck && (
        <p className="text-[10px] text-rose-700">
          Worker may have crashed mid-run. Slack alert fired.
        </p>
      )}
    </div>
  );
}


/** Format a millisecond duration — sub-second in ms, then s, m, h. */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
}


/** Mirror of `formatRelativeFuture` for past timestamps. Used for
 *  "last run was 2h ago" rendering. */
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


/**
 * Format a future date as "in 23 minutes" / "in 6 hours" / "tomorrow".
 * `Intl.RelativeTimeFormat` would do this prettier but it's locale-
 * specific; for VI we keep it short in English-style for ops legibility.
 * The absolute timestamp is in the row's hover title for precision.
 */
function formatRelativeFuture(d: Date): string {
  const ms = d.getTime() - Date.now();
  if (ms <= 0) return "due now";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `in ${sec}s`;
  const min = Math.round(sec / 60);
  if (min < 60) return `in ${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `in ${hr}h`;
  const days = Math.round(hr / 24);
  return `in ${days}d`;
}
