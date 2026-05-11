"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import { type TopKeyRow, useTopApiKeys } from "@/hooks/apiKeys";


// Fixed window options. 24h / 7d / 30d match the api_key_calls
// retention horizon (30d). No "all-time" option because retention
// pruning would already have removed older buckets.
const WINDOWS: Array<{ hours: number; label: string }> = [
  { hours: 1, label: "1h" },
  { hours: 24, label: "24h" },
  { hours: 24 * 7, label: "7d" },
  { hours: 24 * 30, label: "30d" },
];


/**
 * Cross-org API key usage leaderboard. Platform-admin only — requires
 * the `admin` role (ops + Customer Success), not the per-org
 * `Role.ADMIN`. Surfaces:
 *
 *   * Top N keys by total calls in the window.
 *   * Per-key error count + rate.
 *   * Whether the key is revoked (still surfaces the historical row
 *     so ops can see what an offending key did before revocation).
 *
 * Drives capacity planning ("partner X is now 40% of all traffic")
 * and incident response ("which key is hammering us right now").
 */
export default function ApiUsagePage() {
  const [hours, setHours] = useState(24);
  const [limit, setLimit] = useState(20);
  const { data, isLoading, isError, error } = useTopApiKeys(hours, limit);

  const totalCalls = data?.reduce((s, r) => s + r.total_count, 0) ?? 0;
  const totalErrors = data?.reduce((s, r) => s + r.error_count, 0) ?? 0;
  const errorRate = totalCalls > 0 ? totalErrors / totalCalls : 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">API key usage</h2>
        <p className="text-sm text-slate-600">
          Top API keys theo lưu lượng. Bao gồm key đã revoke (vẫn cho thấy
          hoạt động lịch sử trong cửa sổ). Dữ liệu trễ tới 1 phút (writer
          truncate timestamp về phút).
        </p>
      </div>

      {/* ---------- Window + limit toggle ---------- */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Cửa sổ
        </span>
        {WINDOWS.map((w) => (
          <button
            key={w.hours}
            type="button"
            onClick={() => setHours(w.hours)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              hours === w.hours
                ? "bg-blue-600 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {w.label}
          </button>
        ))}
        <span className="ml-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Top
        </span>
        {[10, 25, 50, 100].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => setLimit(n)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              limit === n
                ? "bg-slate-700 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {n}
          </button>
        ))}
      </div>

      {/* ---------- Totals strip ---------- */}
      {data && data.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Tile
            icon={<Activity size={14} />}
            label="Tổng calls (top N)"
            value={totalCalls.toLocaleString("vi-VN")}
          />
          <Tile
            icon={<AlertTriangle size={14} />}
            label="Errors (4xx/5xx + 429)"
            value={`${totalErrors.toLocaleString("vi-VN")} (${(errorRate * 100).toFixed(1)}%)`}
            warn={errorRate >= 0.05}
          />
          <Tile
            icon={<ShieldCheck size={14} />}
            label="Keys hoạt động"
            value={`${data.filter((r) => !r.revoked).length} / ${data.length}`}
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <ErrorPanel error={error as Error | null} />
      ) : !data || data.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
          Không có call nào trong cửa sổ này.
        </p>
      ) : (
        // `overflow-x-auto` (not `overflow-hidden`) so on mobile the
        // 7-column table scrolls horizontally WITHIN its rounded-card
        // wrapper rather than overflowing the viewport. `min-w-[640px]`
        // on the table itself keeps the columns from collapsing into
        // an unreadable accordion below the breakpoint.
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">Key</th>
                <th className="px-4 py-2">Org</th>
                <th className="px-4 py-2 text-right">Calls</th>
                <th className="px-4 py-2 text-right">Errors</th>
                <th className="px-4 py-2 text-right">Error %</th>
                <th className="px-4 py-2">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((row, i) => (
                <UsageRow key={row.id} row={row} rank={i + 1} totalCalls={totalCalls} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function UsageRow({
  row,
  rank,
  totalCalls,
}: {
  row: TopKeyRow;
  rank: number;
  totalCalls: number;
}) {
  const errorPct = row.total_count > 0 ? row.error_count / row.total_count : 0;
  // Bar fill % across all top-N rows so a single dominant key reads
  // visually ("partner X is half the traffic").
  const sharePct = totalCalls > 0 ? (row.total_count / totalCalls) * 100 : 0;
  return (
    <tr className={row.revoked ? "bg-slate-50/60 text-slate-500" : ""}>
      <td className="px-4 py-3 text-xs tabular-nums text-slate-500">{rank}</td>
      <td className="px-4 py-3">
        {/* Click the name → drilldown page with the per-key sparkline +
            hourly breakdown. Wrapping just the name (not the whole
            row) keeps the org-id cell + numeric cells selectable for
            copy-paste, which ops actually does for incident triage. */}
        <Link
          href={`/admin/api-usage/${row.id}`}
          className="font-medium text-slate-900 hover:text-blue-700 hover:underline"
        >
          {row.name}
        </Link>
        <p className="font-mono text-[10px] text-slate-400">aec_{row.prefix}…</p>
      </td>
      <td className="px-4 py-3 font-mono text-[10px] text-slate-500">
        {row.organization_id.slice(0, 8)}…
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-2">
          <div className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-slate-100 sm:block">
            <div
              className="h-full bg-blue-500"
              style={{ width: `${sharePct}%` }}
            />
          </div>
          <span className="tabular-nums">{row.total_count.toLocaleString("vi-VN")}</span>
        </div>
      </td>
      <td className="px-4 py-3 text-right tabular-nums">
        {row.error_count > 0 ? (
          <span className="text-rose-700">{row.error_count}</span>
        ) : (
          <span className="text-slate-400">0</span>
        )}
      </td>
      <td className="px-4 py-3 text-right tabular-nums">
        {row.total_count > 0 ? (
          <span
            className={
              errorPct >= 0.1
                ? "text-rose-700"
                : errorPct >= 0.01
                  ? "text-amber-700"
                  : "text-slate-500"
            }
          >
            {(errorPct * 100).toFixed(1)}%
          </span>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
      <td className="px-4 py-3">
        {row.revoked ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-medium text-rose-800">
            <Trash2 size={10} /> revoked
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
            <ShieldCheck size={10} /> active
          </span>
        )}
      </td>
    </tr>
  );
}


function Tile({
  icon,
  label,
  value,
  warn = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        warn ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-center gap-2 text-slate-500">
        <span className={warn ? "text-amber-600" : "text-slate-400"}>
          {icon}
        </span>
        <span className="text-xs">{label}</span>
      </div>
      <p className="mt-1 text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}


function ErrorPanel({ error }: { error: Error | null }) {
  const msg = error?.message ?? "";
  const isForbidden = msg.includes("403") || /forbidden/i.test(msg);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-medium">Không thể tải usage</p>
        <p className="mt-0.5 text-xs">
          {isForbidden
            ? "Trang này yêu cầu quyền platform-admin (vai trò 'admin'), không phải org-admin."
            : msg || "Vui lòng thử lại sau."}
        </p>
      </div>
    </div>
  );
}
