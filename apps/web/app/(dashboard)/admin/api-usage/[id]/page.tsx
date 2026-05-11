"use client";

/**
 * Per-key usage drilldown — `/admin/api-usage/[id]`.
 *
 * Click a row on the `/admin/api-usage` leaderboard → land here with
 * the key's full hour-bucketed breakdown:
 *
 *   * Sparkline: hour-by-hour calls + errors over the window. Same
 *     `<UsageSparkline>` component the leaderboard inlines, sized
 *     larger here because this is the focal point of the page.
 *
 *   * Totals strip: window calls / errors / error rate. Mirrors
 *     the leaderboard row but unambiguously scoped to this one key.
 *
 *   * Per-bucket table: every hour with non-zero traffic, listing
 *     success + error counts. Triage view — ops can pinpoint "the
 *     spike was at 14:00–15:00".
 *
 * Backend: `GET /api/v1/admin/api-keys/{id}/usage?hours=N` (E2,
 * `services.api_keys.usage_for_key`). Frontend hook is `useApiKeyUsage`.
 *
 * Window selector mirrors the leaderboard's: 1h / 24h / 7d / 30d.
 * No "all-time" because api_key_calls retention prunes at 30d.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Activity, AlertTriangle, ArrowLeft, Clock } from "lucide-react";

import { UsageSparkline } from "@/components/UsageSparkline";
import { useApiKeyUsage } from "@/hooks/apiKeys";


// Same set as the leaderboard. Kept as two separate constants
// (vs imported) so a future change to one window list doesn't have
// to ripple via a barrel import — the lists are documentation-style.
const WINDOWS: Array<{ hours: number; label: string }> = [
  { hours: 1, label: "1h" },
  { hours: 24, label: "24h" },
  { hours: 24 * 7, label: "7d" },
  { hours: 24 * 30, label: "30d" },
];


function formatHour(iso: string): string {
  // The series buckets come back as ISO timestamps anchored at the
  // start of each hour. `vi-VN` locale gives 24h time + dd/mm date —
  // the format ops actually reads when triaging.
  if (!iso) return "—";
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}


export default function ApiKeyUsageDrilldown() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const [hours, setHours] = useState(24);
  const { data, isLoading, isError, error } = useApiKeyUsage(id, hours);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/admin/api-usage"
          className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
        >
          <ArrowLeft size={12} />
          Quay về leaderboard
        </Link>
        <h2 className="mt-2 text-2xl font-bold text-slate-900">
          Telemetry chi tiết
        </h2>
        <p className="font-mono text-[11px] text-slate-500">
          api_key_id: {id}
        </p>
      </div>

      {/* ---------- Window picker ---------- */}
      <div className="flex flex-wrap items-center gap-2">
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
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <ErrorBanner error={error as Error | null} />
      ) : !data ? (
        <p className="text-sm text-slate-500">
          Không có dữ liệu — key có thể chưa được dùng trong cửa sổ này.
        </p>
      ) : (
        <>
          {/* ---------- Totals strip ---------- */}
          <div className="grid gap-3 sm:grid-cols-3">
            <Tile
              icon={<Activity size={14} />}
              label="Tổng calls"
              value={data.total_count.toLocaleString("vi-VN")}
            />
            <Tile
              icon={<AlertTriangle size={14} />}
              label="Errors"
              value={data.error_count.toLocaleString("vi-VN")}
              warn={data.error_rate >= 0.05}
            />
            <Tile
              icon={<Clock size={14} />}
              label="Error rate"
              value={`${(data.error_rate * 100).toFixed(2)}%`}
              warn={data.error_rate >= 0.05}
            />
          </div>

          {/* ---------- Sparkline ---------- */}
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-semibold text-slate-900">
              Lịch sử theo giờ
            </h3>
            <p className="text-[11px] text-slate-500">
              Đường slate = tổng calls; đường rose = errors. Trục Y co dãn
              theo bucket cao nhất — hình dạng quan trọng hơn giá trị tuyệt
              đối, dùng totals strip ở trên cho con số.
            </p>
            <div className="mt-4 flex justify-center">
              {/* Sparkline component takes ApiKeyUsageBucket[] directly.
                  Centred + scaled-up via wrapper styling — the SVG is
                  intrinsically sized so we just give it room. */}
              <div className="w-full max-w-3xl">
                <div className="scale-[3] origin-left">
                  <UsageSparkline buckets={data.series} />
                </div>
              </div>
            </div>
          </section>

          {/* ---------- Per-bucket table ---------- */}
          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Bucket theo giờ
              </h3>
              <p className="text-[11px] text-slate-500">
                {data.series.filter((b) => b.success_count + b.error_count > 0).length}{" "}
                /{data.series.length} bucket có hoạt động
              </p>
            </header>
            {data.series.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-slate-500">
                Không có call nào trong cửa sổ này.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Giờ</th>
                    <th className="px-4 py-2 text-right">Success</th>
                    <th className="px-4 py-2 text-right">Errors</th>
                    <th className="px-4 py-2 text-right">Error %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.series
                    // Filter zero-traffic buckets so the table is
                    // signal-only. The sparkline above shows the full
                    // window shape; the table is for "which hour was
                    // the spike" — empty rows would dilute that.
                    .filter((b) => b.success_count + b.error_count > 0)
                    .map((b) => {
                      const total = b.success_count + b.error_count;
                      const errPct = total > 0 ? b.error_count / total : 0;
                      return (
                        <tr key={b.hour}>
                          <td className="px-4 py-2 font-mono text-xs text-slate-700">
                            {formatHour(b.hour)}
                          </td>
                          <td className="px-4 py-2 text-right tabular-nums">
                            {b.success_count.toLocaleString("vi-VN")}
                          </td>
                          <td className="px-4 py-2 text-right tabular-nums">
                            {b.error_count > 0 ? (
                              <span className="text-rose-700">
                                {b.error_count.toLocaleString("vi-VN")}
                              </span>
                            ) : (
                              <span className="text-slate-400">0</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-right tabular-nums text-xs">
                            <span
                              className={
                                errPct >= 0.1
                                  ? "text-rose-700 font-semibold"
                                  : errPct >= 0.05
                                    ? "text-amber-700"
                                    : "text-slate-500"
                              }
                            >
                              {(errPct * 100).toFixed(1)}%
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}


function Tile({
  icon,
  label,
  value,
  warn,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div
      className={`flex items-start gap-3 rounded-xl border p-4 ${
        warn
          ? "border-rose-200 bg-rose-50"
          : "border-slate-200 bg-white"
      }`}
    >
      <div
        className={
          warn
            ? "rounded-md bg-rose-100 p-2 text-rose-700"
            : "rounded-md bg-slate-100 p-2 text-slate-600"
        }
      >
        {icon}
      </div>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </p>
        <p
          className={`mt-1 text-xl font-semibold tabular-nums ${
            warn ? "text-rose-900" : "text-slate-900"
          }`}
        >
          {value}
        </p>
      </div>
    </div>
  );
}


function ErrorBanner({ error }: { error: Error | null }) {
  const msg = error?.message ?? "lỗi không xác định";
  const isForbidden = /403|forbidden/i.test(msg);
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {isForbidden
        ? "Bạn cần quyền admin để xem telemetry chi tiết."
        : `Không thể tải telemetry: ${msg}`}
    </div>
  );
}
