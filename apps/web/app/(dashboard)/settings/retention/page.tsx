"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Archive,
  Calendar,
  CheckCircle2,
  Clock,
  Database,
  Loader2,
  PlayCircle,
  ShieldAlert,
} from "lucide-react";

import {
  type RetentionRunSummary,
  type RetentionStat,
  useRetentionRunNow,
  useRetentionStatus,
} from "@/hooks/retention";


// Friendlier display names for the four managed tables. The hook
// returns raw table names — those are right for ops, but a Vietnamese
// admin reads "Webhook deliveries" more easily than `webhook_deliveries`.
const TABLE_LABEL: Record<string, string> = {
  audit_events: "Nhật ký kiểm tra",
  webhook_deliveries: "Webhook deliveries",
  search_queries: "Lịch sử tìm kiếm",
  import_jobs: "Lịch sử nhập dữ liệu",
};


function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const days = Math.floor((Date.now() - date.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 1) return "hôm nay";
  if (days < 30) return `${days} ngày trước`;
  if (days < 365) return `${Math.floor(days / 30)} tháng trước`;
  return `${Math.floor(days / 365)} năm trước`;
}


export default function RetentionPage() {
  const { data: stats, isLoading, isError, error } = useRetentionStatus();
  const runNow = useRetentionRunNow();
  const [lastRun, setLastRun] = useState<RetentionRunSummary[] | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Retention &amp; archival</h2>
        <p className="text-sm text-slate-600">
          Các bảng telemetry và audit tự prune theo TTL hàng đêm (cron 03:00 UTC).
          Mỗi bảng được giới hạn 10.000 dòng / lần để không lock bảng quá lâu.
          Bảng có cờ <Archive size={11} className="inline" /> được archive sang
          S3 dưới dạng JSONL trước khi DELETE.
        </p>
      </div>

      {/* ---------- Run now ---------- */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Chạy thủ công</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Cùng job với cron hàng đêm. Hữu ích sau khi triển khai retention
            lên một org đã có nhiều năm dữ liệu cần dọn.
          </p>
        </div>
        <button
          type="button"
          onClick={() =>
            runNow.mutate(undefined, {
              onSuccess: (d) => setLastRun(d.tables),
            })
          }
          disabled={runNow.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {runNow.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <PlayCircle size={14} />
          )}
          Prune ngay
        </button>
      </section>

      {lastRun && <RunSummary summary={lastRun} />}

      {/* ---------- Status table ---------- */}
      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <ErrorPanel error={error as Error | null} />
      ) : !stats || stats.length === 0 ? (
        <p className="text-sm text-slate-500">Không có bảng nào được cấu hình.</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {stats.map((s) => (
            <TableCard key={s.table} stat={s} />
          ))}
        </div>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function TableCard({ stat }: { stat: RetentionStat }) {
  const overduePct = stat.row_count
    ? Math.round((stat.overdue_count / stat.row_count) * 100)
    : 0;
  // Visual cue: a table with a meaningful overdue backlog gets the
  // amber treatment so an admin doing a quick scan notices it.
  const warn = stat.overdue_count > 0;
  return (
    <article
      className={`rounded-xl border p-4 ${
        warn ? "border-amber-300 bg-amber-50/40" : "border-slate-200 bg-white"
      }`}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Database size={14} className="text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-900">
            {TABLE_LABEL[stat.table] ?? stat.table}
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {stat.archived_to_s3 && (
            <span
              title="Archive to S3 before DELETE"
              className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-800"
            >
              <Archive size={10} /> S3
            </span>
          )}
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700">
            <Clock size={10} /> {stat.ttl_days}d
          </span>
        </div>
      </header>
      <p className="mt-0.5 font-mono text-[10px] text-slate-400">{stat.table}</p>

      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-slate-500">Tổng dòng</dt>
          <dd className="mt-0.5 font-semibold text-slate-800 tabular-nums">
            {stat.row_count.toLocaleString("vi-VN")}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Quá hạn</dt>
          <dd
            className={`mt-0.5 font-semibold tabular-nums ${
              warn ? "text-amber-800" : "text-slate-800"
            }`}
          >
            {stat.overdue_count.toLocaleString("vi-VN")}{" "}
            {stat.row_count > 0 && (
              <span className="text-[10px] font-normal text-slate-500">
                ({overduePct}%)
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Lần prune kế</dt>
          <dd className="mt-0.5 font-semibold text-slate-800 tabular-nums">
            {stat.projected_next_prune_count.toLocaleString("vi-VN")}
            {stat.projected_next_prune_count >= 10_000 && "+"}
          </dd>
        </div>
      </dl>

      <p className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-500">
        <Calendar size={11} /> Dòng cũ nhất: {formatRelative(stat.oldest_at)}
      </p>
    </article>
  );
}


function RunSummary({ summary }: { summary: RetentionRunSummary[] }) {
  const total = summary.reduce((s, t) => s + t.deleted_count, 0);
  const errors = summary.filter((t) => t.error);
  return (
    <section
      className={`rounded-xl border p-4 ${
        errors.length > 0
          ? "border-amber-200 bg-amber-50"
          : "border-emerald-200 bg-emerald-50"
      }`}
    >
      <header className="flex items-center gap-2">
        {errors.length > 0 ? (
          <AlertTriangle size={16} className="text-amber-600" />
        ) : (
          <CheckCircle2 size={16} className="text-emerald-600" />
        )}
        <h3 className="text-sm font-semibold text-slate-900">
          Đã xoá {total.toLocaleString("vi-VN")} dòng
          {errors.length > 0 && ` · ${errors.length} bảng lỗi`}
        </h3>
      </header>
      <ul className="mt-2 space-y-1 text-xs">
        {summary.map((t) => (
          <li key={t.table} className="flex items-center justify-between gap-2">
            <span className="font-mono text-slate-600">{t.table}</span>
            <span className="tabular-nums text-slate-700">
              {t.error ? (
                <span className="text-amber-700">⚠ {t.error}</span>
              ) : (
                <>
                  {t.deleted_count.toLocaleString("vi-VN")} dòng
                  {t.archive_key && (
                    <span className="ml-2 text-[10px] text-slate-500">
                      → {t.archive_key}
                    </span>
                  )}
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}


function ErrorPanel({ error }: { error: Error | null }) {
  const msg = error?.message ?? "";
  const isForbidden = msg.includes("403") || /forbidden/i.test(msg);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-medium">Không thể tải retention status</p>
        <p className="mt-0.5 text-xs">
          {isForbidden
            ? "Trang này yêu cầu quyền platform-admin (vai trò 'admin'), không phải org-admin."
            : msg || "Vui lòng thử lại sau."}
        </p>
      </div>
    </div>
  );
}
