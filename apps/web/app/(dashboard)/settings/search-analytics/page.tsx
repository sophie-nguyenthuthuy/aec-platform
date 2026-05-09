"use client";

import { useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Search,
  ShieldAlert,
  TrendingDown,
  Users,
} from "lucide-react";

import {
  type MatchedDistributionRow,
  type NoResultQueryRow,
  type ScopeDistributionRow,
  type SearchAnalyticsTotals,
  type TopQueryRow,
  useSearchAnalytics,
} from "@/hooks/searchAnalytics";


// Window-toggle options. Capped at 90d because:
//   * the partial index on `(organization_id, created_at DESC)` keeps
//     30d-window queries fast; longer windows cross more pages.
//   * search-query content goes stale fast — what matters is "what
//     are users typing this MONTH", not last quarter.
const WINDOW_OPTIONS: Array<{ days: number; label: string }> = [
  { days: 7, label: "7 ngày" },
  { days: 30, label: "30 ngày" },
  { days: 90, label: "90 ngày" },
];


// Scope label dictionary — mirror of `SCOPE_META` in CommandPalette,
// kept duplicated so this page doesn't import a 5kb visual component
// just to read its label map. Adding a scope means editing both — a
// small price for not coupling an admin page to a UI component.
const SCOPE_LABEL: Record<string, string> = {
  documents: "Tài liệu",
  regulations: "Quy chuẩn",
  defects: "Lỗi",
  rfis: "RFI",
  proposals: "Đề xuất",
};


// matched_on label dictionary. Same source-of-truth concern as scopes
// above — `MatchChip` in CommandPalette has the canonical chip; we
// just need text labels here.
const MATCHED_LABEL: Record<string, string> = {
  keyword: "Khớp từ khoá",
  vector: "Khớp ngữ nghĩa",
  both: "Cả hai (cao nhất)",
};


export default function SearchAnalyticsPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading, isError, error } = useSearchAnalytics({ days, top_n: 20 });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Phân tích tìm kiếm</h2>
        <p className="text-sm text-slate-600">
          Truy vấn nào người dùng gõ nhiều nhất, truy vấn nào trả về 0 kết
          quả (gap nội dung), và lai (keyword + vector) có thực sự thắng
          hay không.
        </p>
      </div>

      {/* ---------- Window toggle ---------- */}
      <div className="flex flex-wrap gap-1.5">
        {WINDOW_OPTIONS.map((opt) => (
          <button
            key={opt.days}
            type="button"
            onClick={() => setDays(opt.days)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              days === opt.days
                ? "bg-blue-600 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* ---------- Loading / error / empty ---------- */}
      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <ErrorPanel error={error as Error | null} />
      ) : !data ? null : data.totals.total_searches === 0 ? (
        <EmptyState />
      ) : (
        <>
          <TotalsRow totals={data.totals} />
          <div className="grid gap-6 lg:grid-cols-2">
            <TopQueriesCard rows={data.top_queries} />
            <NoResultCard rows={data.no_result_queries} />
            <ScopeCard rows={data.scope_distribution} />
            <MatchedCard rows={data.matched_distribution} />
          </div>
        </>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function TotalsRow({ totals }: { totals: SearchAnalyticsTotals }) {
  // Three-tile summary above the per-breakdown cards. `empty_searches`
  // is rendered as a percent so a spike at 30% reads as alarming
  // without the user doing the division in their head.
  const emptyPct = totals.total_searches
    ? Math.round((totals.empty_searches / totals.total_searches) * 100)
    : 0;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <SummaryTile
        icon={<Search size={16} />}
        label="Tổng số lượt tìm"
        value={totals.total_searches.toLocaleString("vi-VN")}
      />
      <SummaryTile
        icon={<TrendingDown size={16} />}
        label="0 kết quả"
        value={`${totals.empty_searches.toLocaleString("vi-VN")} (${emptyPct}%)`}
        warn={emptyPct >= 25}
      />
      <SummaryTile
        icon={<Users size={16} />}
        label="Người dùng đã tìm"
        value={totals.unique_users.toLocaleString("vi-VN")}
      />
    </div>
  );
}


function SummaryTile({
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
        <span className={warn ? "text-amber-600" : "text-slate-400"}>{icon}</span>
        <span className="text-xs">{label}</span>
      </div>
      <p className="mt-1 text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}


function TopQueriesCard({ rows }: { rows: TopQueryRow[] }) {
  return (
    <Card title="Truy vấn phổ biến" icon={<BarChart3 size={14} />}>
      {rows.length === 0 ? (
        <EmptyHint />
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-[11px] uppercase text-slate-500">
            <tr>
              <th className="pb-2">Truy vấn</th>
              <th className="pb-2 text-right">Lượt</th>
              <th className="pb-2 text-right">TB kết quả</th>
              <th className="pb-2 text-right">Trống</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => (
              <tr key={r.query}>
                <td className="py-1.5">
                  <span className="font-mono text-xs text-slate-800">
                    {r.query}
                  </span>
                </td>
                <td className="py-1.5 text-right tabular-nums">{r.run_count}</td>
                <td className="py-1.5 text-right tabular-nums">
                  {r.avg_results.toFixed(1)}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {r.empty_count > 0 ? (
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800">
                      {r.empty_count}
                    </span>
                  ) : (
                    <span className="text-slate-400">0</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}


function NoResultCard({ rows }: { rows: NoResultQueryRow[] }) {
  // A non-zero list here is the actionable one — every row is a
  // direct content-gap signal: users typed it expecting something,
  // we returned nothing. Highest-frequency rows go first.
  return (
    <Card
      title="Truy vấn 0 kết quả"
      icon={<TrendingDown size={14} />}
      description="Gap nội dung — người dùng tìm nhưng không thấy gì."
    >
      {rows.length === 0 ? (
        <p className="text-xs text-slate-500">
          Không có truy vấn nào trả về 0 kết quả trong cửa sổ này 🎉
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-[11px] uppercase text-slate-500">
            <tr>
              <th className="pb-2">Truy vấn</th>
              <th className="pb-2 text-right">Lượt</th>
              <th className="pb-2 text-right">Lần cuối</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => (
              <tr key={r.query}>
                <td className="py-1.5">
                  <span className="font-mono text-xs text-slate-800">
                    {r.query}
                  </span>
                </td>
                <td className="py-1.5 text-right tabular-nums">{r.run_count}</td>
                <td className="py-1.5 text-right text-xs text-slate-500">
                  {r.last_run
                    ? new Date(r.last_run).toLocaleDateString("vi-VN")
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}


function ScopeCard({ rows }: { rows: ScopeDistributionRow[] }) {
  // Bar-chart-by-bg-color: each row's bar fills its td proportionally
  // to the row count. Avoids pulling in a chart lib for one card.
  const total = rows.reduce((s, r) => s + r.run_count, 0) || 1;
  return (
    <Card
      title="Module được tìm nhiều nhất"
      icon={<BarChart3 size={14} />}
      description="Module có nhiều rows nhất trên `top_scope` mỗi lần tìm."
    >
      {rows.length === 0 ? (
        <EmptyHint />
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => {
            const pct = Math.round((r.run_count / total) * 100);
            return (
              <li key={r.scope}>
                <div className="flex items-baseline justify-between text-xs">
                  <span className="font-medium text-slate-700">
                    {SCOPE_LABEL[r.scope] ?? r.scope}
                  </span>
                  <span className="tabular-nums text-slate-500">
                    {r.run_count} · {pct}%
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full bg-blue-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}


function MatchedCard({ rows }: { rows: MatchedDistributionRow[] }) {
  // The hybrid-ROI tile. If `vector`+`both` is dwarfed by `keyword`,
  // we either turned off the embed key, the index is broken, or the
  // user-typed queries don't benefit from semantics. All three are
  // worth investigating — surface the raw split.
  const total = rows.reduce((s, r) => s + r.run_count, 0) || 1;
  return (
    <Card
      title="Lai vs từ khoá"
      icon={<BarChart3 size={14} />}
      description="Kết quả tìm được khớp qua arm nào (cộng dồn các row)."
    >
      {rows.length === 0 ? (
        <p className="text-xs text-slate-500">
          Chưa có dữ liệu khớp trong cửa sổ này (vector arm có thể đang tắt vì
          thiếu OPENAI_API_KEY).
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => {
            const pct = Math.round((r.run_count / total) * 100);
            const tone =
              r.label === "both"
                ? "bg-emerald-500"
                : r.label === "vector"
                  ? "bg-violet-500"
                  : "bg-slate-500";
            return (
              <li key={r.label}>
                <div className="flex items-baseline justify-between text-xs">
                  <span className="font-medium text-slate-700">
                    {MATCHED_LABEL[r.label] ?? r.label}
                  </span>
                  <span className="tabular-nums text-slate-500">
                    {r.run_count} · {pct}%
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}


// ---------- Layout primitives ----------


function Card({
  title,
  icon,
  description,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <header className="mb-3">
        <div className="flex items-center gap-2 text-slate-700">
          <span className="text-slate-400">{icon}</span>
          <h3 className="text-sm font-semibold">{title}</h3>
        </div>
        {description && (
          <p className="mt-0.5 text-xs text-slate-500">{description}</p>
        )}
      </header>
      {children}
    </section>
  );
}


function ErrorPanel({ error }: { error: Error | null }) {
  // Most likely cause: caller is `member`/`viewer`. Match the audit
  // page's error treatment so admin-gated pages feel consistent.
  const msg = error?.message ?? "";
  const isForbidden = msg.includes("403") || /forbidden/i.test(msg);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-medium">Không thể tải phân tích</p>
        <p className="mt-0.5 text-xs">
          {isForbidden
            ? "Bạn cần quyền admin để xem trang này. Liên hệ owner."
            : msg || "Vui lòng thử lại sau."}
        </p>
      </div>
    </div>
  );
}


function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
      <Search size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
      <p className="text-sm font-medium text-slate-700">
        Chưa có lượt tìm kiếm nào trong cửa sổ này.
      </p>
      <p className="mt-1 text-xs text-slate-500">
        Mỗi lần người dùng nhấn Cmd+K và gõ truy vấn, một row sẽ được ghi vào
        bảng telemetry. Quay lại trang này sau một vài lượt sử dụng.
      </p>
    </div>
  );
}


function EmptyHint() {
  return (
    <div className="flex items-start gap-2 text-xs text-slate-500">
      <AlertTriangle size={12} className="mt-0.5 shrink-0 text-slate-400" />
      <p>Không có dữ liệu trong cửa sổ này.</p>
    </div>
  );
}
