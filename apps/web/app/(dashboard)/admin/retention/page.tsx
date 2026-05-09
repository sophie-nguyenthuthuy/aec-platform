"use client";

/**
 * Data retention dashboard — `/admin/retention`.
 *
 * Read-only telemetry of `services.retention.RETENTION_POLICIES` +
 * what the next prune tick will delete. v1 doesn't surface a
 * per-tenant override (no `retention_policies` table yet) — just
 * "here's what the cron will do tonight."
 *
 * Why a dedicated page rather than a row on `/admin/crons`:
 *   * The data is structured (per-table TTL + counts) — a row on the
 *     cron registry would compress to "retention_prune_cron — 30d"
 *     which doesn't surface the per-table breakdown ops actually
 *     care about ("audit_events has 12M rows but only 1k are
 *     overdue — the prune is keeping up").
 *   * Operators triaging an audit-table outage want to see the
 *     prune state alongside the row count, not buried inside the
 *     cron drilldown.
 *
 * Run-now button: fires `POST /admin/retention/run` synchronously.
 * Useful during initial deploy of a new policy (one-shot catch-up
 * pruning), not for steady-state ops.
 */

import { useState } from "react";
import {
  AlertCircle,
  Archive,
  CheckCircle2,
  ChevronLeft,
  Database,
  Loader2,
  PlayCircle,
} from "lucide-react";
import Link from "next/link";

import {
  type RetentionStatusRow,
  useRetentionRunNow,
  useRetentionStatus,
} from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


export default function RetentionPage(): JSX.Element {
  const session = useSession();
  const status = useRetentionStatus();
  const isAdmin =
    session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Trang này chỉ dành cho admin nền tảng.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <Link
        href="/admin"
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
      >
        <ChevronLeft size={14} />
        Admin hub
      </Link>

      <header className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Archive size={20} className="text-blue-600" />
            <h1 className="text-2xl font-bold text-slate-900">
              Data retention
            </h1>
          </div>
          <p className="max-w-2xl text-sm text-slate-600">
            Per-table retention status. Mỗi table được prune nightly lúc
            03:00 UTC bởi <code>retention_prune_cron</code>. Cap 10k
            rows/table/run — tenant churned-up theo nhiều ngày thay vì lock
            table.
          </p>
        </div>
        <RunNowButton />
      </header>

      {status.isLoading && (
        <p className="text-sm text-slate-500">Đang tải...</p>
      )}

      {status.isError && (
        <ErrorBanner error={status.error as Error | null} />
      )}

      {status.data && (
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          {status.data.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-slate-500">
              Không có policy nào trong{" "}
              <code>services.retention.RETENTION_POLICIES</code>.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Table</th>
                    <th className="px-4 py-2 text-right">Rows</th>
                    <th className="px-4 py-2">Oldest</th>
                    <th className="px-4 py-2 text-right">TTL</th>
                    <th className="px-4 py-2 text-right">Overdue</th>
                    <th className="px-4 py-2 text-right">Next prune</th>
                    <th className="px-4 py-2">Archive</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {status.data.map((row) => (
                    <RetentionRow key={row.table} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function RunNowButton(): JSX.Element {
  const run = useRetentionRunNow();
  const [justRan, setJustRan] = useState(false);

  function handleClick() {
    if (
      !confirm(
        "Run retention prune NOW? This deletes overdue rows from every managed table (capped at 10k rows/table). Useful for initial cleanup; not normally needed in steady state.",
      )
    ) {
      return;
    }
    run.mutate(undefined, {
      onSuccess: () => {
        setJustRan(true);
        setTimeout(() => setJustRan(false), 6000);
      },
    });
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={run.isPending || justRan}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition ${
        justRan
          ? "border border-emerald-300 bg-emerald-50 text-emerald-800"
          : "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:opacity-50"
      }`}
      title="Run retention_prune_cron synchronously. Capped at 10k rows/table/run."
    >
      {run.isPending ? (
        <>
          <Loader2 size={12} className="animate-spin" />
          Pruning...
        </>
      ) : justRan ? (
        <>
          <CheckCircle2 size={12} />
          {summariseLastRun(run.data?.tables ?? [])}
        </>
      ) : (
        <>
          <PlayCircle size={12} />
          Run prune now
        </>
      )}
    </button>
  );
}


function RetentionRow({ row }: { row: RetentionStatusRow }) {
  // Highlight when overdue is non-trivial relative to the cap — that's
  // the case where tomorrow's prune won't catch up. Operationally
  // surface so ops can tune the policy or the cap.
  const overdueOverflow = row.overdue_count > row.projected_next_prune_count;

  return (
    <tr className="align-top">
      <td className="px-4 py-2 font-mono text-xs text-slate-800">
        <div className="flex items-center gap-1.5">
          <Database size={12} className="text-slate-400" />
          {row.table}
        </div>
      </td>
      <td className="px-4 py-2 text-right font-mono text-xs text-slate-700">
        {row.row_count.toLocaleString()}
      </td>
      <td className="px-4 py-2 text-xs text-slate-700">
        {row.oldest_at ? (
          <>
            <p>{new Date(row.oldest_at).toLocaleDateString("vi-VN")}</p>
            <p className="mt-0.5 text-[10px] text-slate-400">
              {formatAge(row.oldest_at)}
            </p>
          </>
        ) : (
          <span className="text-slate-400">empty</span>
        )}
      </td>
      <td className="px-4 py-2 text-right font-mono text-xs text-slate-700">
        {row.ttl_days}d
      </td>
      <td className="px-4 py-2 text-right font-mono text-xs text-slate-700">
        {row.overdue_count > 0 ? (
          <span
            className={
              overdueOverflow ? "font-semibold text-amber-700" : ""
            }
          >
            {row.overdue_count.toLocaleString()}
          </span>
        ) : (
          <span className="text-slate-400">0</span>
        )}
      </td>
      <td className="px-4 py-2 text-right font-mono text-xs text-slate-700">
        {row.projected_next_prune_count > 0 ? (
          row.projected_next_prune_count.toLocaleString()
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
      <td className="px-4 py-2">
        {row.archived_to_s3 ? (
          <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-800">
            S3
          </span>
        ) : (
          <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
            none
          </span>
        )}
      </td>
    </tr>
  );
}


function ErrorBanner({ error }: { error: Error | null }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <p>
        Không thể tải retention status:{" "}
        {error?.message ?? "lỗi không xác định"}
      </p>
    </div>
  );
}


// ---------- Pure helpers ----------


function formatAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "future";
  const days = Math.round(ms / (1000 * 60 * 60 * 24));
  if (days < 1) return "today";
  if (days < 60) return `${days}d ago`;
  if (days < 730) return `${Math.round(days / 30)}mo ago`;
  return `${Math.round(days / 365)}y ago`;
}


function summariseLastRun(
  tables: Array<{ table: string; deleted_count: number; error?: string }>,
): string {
  const total = tables.reduce((sum, t) => sum + (t.deleted_count ?? 0), 0);
  const errors = tables.filter((t) => t.error).length;
  if (errors > 0) {
    return `Pruned ${total.toLocaleString()} (${errors} errors)`;
  }
  return `Pruned ${total.toLocaleString()} rows`;
}
