"use client";

/**
 * CODEGUARD per-tenant quota dashboard.
 *
 * The `<QuotaStatusBanner>` (mounted in the dashboard-root layout, so
 * it shows up across every LLM-touching surface) already surfaces
 * "you're at X%" when usage crosses 80% — that's reactive. This page
 * is the *planning* surface: how much have we spent, what's the cap,
 * how many days until it resets, and what does the recent trend look
 * like? A tenant admin who hits this page wants to answer "are we on
 * track to blow through this month?" without filing an ops ticket.
 *
 * What renders:
 *   - Per-dimension progress bars for input + output, even when one's
 *     well below the warn threshold. Unlike the banner (which hides
 *     under 80%), this page wants to give the user the full picture.
 *   - Period start + days-until-reset countdown. The cap resets at
 *     midnight UTC on the 1st, so we compute against UTC, not the
 *     user's local time — otherwise admins in late timezones would
 *     see "0 days remaining" while the cap is still active.
 *   - Token-limit numbers spelled out, formatted with vi-VN grouping
 *     (matches the locale used elsewhere in the app).
 *   - 3-month usage history strip — bar chart per dimension, so a
 *     pattern like "we keep hitting 90% in the last week of every
 *     month" is visible at a glance.
 *
 * What's deliberately out of scope:
 *   - Editing limits — that's an ops concern via the CLI, not a
 *     tenant-self-serve operation. (See `scripts/codeguard_quotas.py`.)
 *   - Alerting / notifications — the banner already covers
 *     in-the-moment warnings; this page is for context.
 *   - Per-user breakdown — usage is org-scoped only.
 */

import { useState } from "react";

import { Loader2, AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";

import {
  useCodeguardQuota,
  useCodeguardQuotaHistory,
  useCodeguardQuotaTopUsers,
  type CodeguardQuota,
  type CodeguardQuotaHistory,
  type CodeguardQuotaTopUsers,
  type QuotaHistoryEntry,
  type QuotaTopUser,
  type QuotaTopUserRoute,
} from "@/hooks/codeguard";

const MONTHS_OF_HISTORY = 3;

export default function CodeguardQuotaPage() {
  const quota = useCodeguardQuota();
  const history = useCodeguardQuotaHistory(MONTHS_OF_HISTORY);

  if (quota.isLoading || history.isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-sm text-slate-600"
        role="status"
        aria-live="polite"
      >
        <Loader2 size={16} className="animate-spin" /> Đang tải hạn mức…
      </div>
    );
  }
  if (quota.isError || !quota.data) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
        <AlertTriangle size={16} className="mr-2 inline-block text-red-700" />
        Lỗi khi tải hạn mức. Thử lại sau ít phút.
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header>
        <h2 className="text-2xl font-bold text-slate-900">Hạn mức CODEGUARD</h2>
        <p className="text-sm text-slate-600">
          Theo dõi mức sử dụng token và lập kế hoạch theo tháng.
        </p>
      </header>

      {quota.data.unlimited ? (
        <UnlimitedNotice />
      ) : (
        <>
          <CurrentMonthCard quota={quota.data} />
          {history.data ? <HistoryStrip history={history.data} /> : null}
          {/* Top consumers panel — only renders for capped orgs (the
              question "who pushed us toward the cap?" is meaningless
              for unlimited orgs). Lazy on its own hook so a slow DB
              read doesn't delay the banner above it. Errors degrade
              silently — top-users is decoration, not load-bearing. */}
          <TopConsumersPanel />
        </>
      )}
    </div>
  );
}

// ---------- Top consumers (per-user spend ranking) ---------------------

/**
 * Per-user spend ranking for the org's CURRENT period. Mounts beneath
 * the trend strip with `breakdown=true` so each row can expand to
 * show per-route attribution (which routes drove this user's spend).
 *
 * Why request breakdown by default: this page is the "planning
 * surface" — admins land here when they want to drill into spend.
 * The breakdown query is one extra round-trip; well worth the
 * latency for the question it answers ("did this user's 80k tokens
 * come from heavy /scan or runaway /query?").
 *
 * Errors return null — top-users is a decoration panel; a transient
 * DB blip on this read shouldn't make the whole page look broken
 * when the actual cap data above it is fine.
 */
function TopConsumersPanel() {
  const top = useCodeguardQuotaTopUsers(10, { breakdown: true });
  if (top.isLoading) {
    return (
      <div className="text-xs text-slate-500">
        <Loader2 size={12} className="mr-1 inline-block animate-spin" />
        Đang tải danh sách người dùng…
      </div>
    );
  }
  if (top.isError || !top.data) return null;
  return <TopConsumersTable data={top.data} />;
}

function TopConsumersTable({ data }: { data: CodeguardQuotaTopUsers }) {
  if (data.users.length === 0) {
    return (
      <section
        className="rounded-xl border border-slate-200 bg-white p-6"
        aria-labelledby="quota-top-users-heading"
      >
        <h3 id="quota-top-users-heading" className="text-lg font-semibold text-slate-900">
          Người dùng tiêu nhiều token nhất
        </h3>
        <p className="mt-2 text-sm text-slate-600">
          Chưa có dữ liệu sử dụng trong kỳ này.
        </p>
      </section>
    );
  }
  return (
    <section
      className="rounded-xl border border-slate-200 bg-white p-6"
      aria-labelledby="quota-top-users-heading"
    >
      <div className="flex items-baseline justify-between">
        <h3
          id="quota-top-users-heading"
          className="text-lg font-semibold text-slate-900"
        >
          Người dùng tiêu nhiều token nhất
        </h3>
        <span className="text-xs text-slate-500">
          Top {data.users.length} trong kỳ hiện tại
        </span>
      </div>
      <table className="mt-4 w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="py-2 font-medium" />
            <th scope="col" className="py-2 font-medium">
              Người dùng
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Input
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Output
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Tổng
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.users.map((u) => (
            <TopConsumerRow key={u.user_id} user={u} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

function TopConsumerRow({ user }: { user: QuotaTopUser }) {
  const [expanded, setExpanded] = useState(false);
  // Empty email = user was deleted between the spend and the read
  // (CASCADE wiped them; LEFT JOIN preserves the spend attribution
  // but the user row is gone). Render a placeholder so the row is
  // still legible.
  const display = user.email || `(người dùng đã xóa: ${user.user_id.slice(0, 8)}…)`;
  // The breakdown is present (possibly empty array) when the hook
  // requested it. Empty array = the user has aggregate spend but
  // no per-route breakdown rows yet — happens for usage recorded
  // before migration 0040 added the by-route table. Hide the
  // expander rather than showing an "empty breakdown" UI surface.
  const hasBreakdown = Array.isArray(user.routes) && user.routes.length > 0;

  return (
    <>
      <tr className={hasBreakdown ? "cursor-pointer hover:bg-slate-50" : undefined}>
        <td className="py-2 pr-2 align-top">
          {hasBreakdown ? (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              aria-label={expanded ? "Thu gọn" : "Mở rộng"}
              aria-expanded={expanded}
              className="text-slate-500 hover:text-slate-800"
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          ) : null}
        </td>
        <td className="py-2 text-slate-800">{display}</td>
        <td className="py-2 text-right tabular-nums text-slate-700">
          {user.input_tokens.toLocaleString("vi-VN")}
        </td>
        <td className="py-2 text-right tabular-nums text-slate-700">
          {user.output_tokens.toLocaleString("vi-VN")}
        </td>
        <td className="py-2 text-right font-medium tabular-nums text-slate-900">
          {user.total_tokens.toLocaleString("vi-VN")}
        </td>
      </tr>
      {expanded && hasBreakdown ? (
        <tr>
          <td className="py-2" />
          <td colSpan={4} className="pb-3">
            <RouteBreakdownTable routes={user.routes ?? []} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function RouteBreakdownTable({ routes }: { routes: QuotaTopUserRoute[] }) {
  // Pre-rendered as a nested table rather than a plain list so the
  // alignment matches the parent — operators scanning the column
  // can quickly compare scan-vs-query spend across users without
  // re-parsing the layout per row.
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-slate-500">
        <tr>
          <th scope="col" className="py-1 font-medium">
            Route
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Input
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Output
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Tổng
          </th>
        </tr>
      </thead>
      <tbody>
        {routes.map((r) => (
          <tr key={r.route_key} className="text-slate-600">
            <td className="py-1">
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700">
                /{r.route_key}
              </code>
            </td>
            <td className="py-1 text-right tabular-nums">
              {r.input_tokens.toLocaleString("vi-VN")}
            </td>
            <td className="py-1 text-right tabular-nums">
              {r.output_tokens.toLocaleString("vi-VN")}
            </td>
            <td className="py-1 text-right tabular-nums font-medium text-slate-800">
              {r.total_tokens.toLocaleString("vi-VN")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------- Unlimited path -----------------------------------------------

function UnlimitedNotice() {
  // Org has no quota row at all → nothing to show beyond a one-liner.
  // Don't render the progress + history sections; they'd be confusing
  // empty boxes. The banner also hides for unlimited orgs, so this
  // page is the only place a tenant admin can confirm "yep, no cap."
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-700">
      Tổ chức của bạn hiện không bị giới hạn token cho CODEGUARD. Liên hệ quản trị
      để cấu hình hạn mức nếu cần.
    </div>
  );
}

// ---------- Current month ------------------------------------------------

function CurrentMonthCard({ quota }: { quota: CodeguardQuota }) {
  const periodStart = quota.period_start;
  const days = daysUntilNextMonth(periodStart);

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white p-6"
      aria-labelledby="quota-current-heading"
    >
      <div className="flex items-baseline justify-between">
        <h3
          id="quota-current-heading"
          className="text-lg font-semibold text-slate-900"
        >
          Tháng hiện tại
        </h3>
        {/* Period + countdown — surface both because either alone is
            ambiguous (period_start is the calendar fact; countdown is
            the actionable piece). */}
        <div className="text-xs text-slate-500">
          {periodStart ? (
            <>
              <span>Kỳ: {formatDateVi(periodStart)}</span>
              <span className="mx-2">•</span>
              <span>{days} ngày nữa reset</span>
            </>
          ) : (
            <span>Chưa có kỳ tính</span>
          )}
        </div>
      </div>

      <div className="mt-4 space-y-5">
        <DimensionRow
          label="Token đầu vào (input)"
          dimension={quota.input}
          unlimitedHint="Không giới hạn input."
        />
        <DimensionRow
          label="Token đầu ra (output)"
          dimension={quota.output}
          unlimitedHint="Không giới hạn output."
        />
      </div>
    </section>
  );
}

function DimensionRow({
  label,
  dimension,
  unlimitedHint,
}: {
  label: string;
  dimension: CodeguardQuota["input"];
  unlimitedHint: string;
}) {
  // Unlimited on this dimension → render the row (so the user still
  // sees the dimension exists) but skip the bar (no meaningful
  // percentage to draw).
  if (!dimension || dimension.percent === null || dimension.limit === null) {
    return (
      <div>
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-medium text-slate-800">{label}</span>
          <span className="text-xs text-slate-500">{unlimitedHint}</span>
        </div>
      </div>
    );
  }

  const pct = dimension.percent;
  const clamped = Math.max(0, Math.min(100, pct));
  // Color band: same thresholds as the banner so the page's color
  // language doesn't drift from the alert language.
  const isCritical = pct >= 95;
  const isWarn = pct >= 80;
  const barClass = isCritical
    ? "bg-red-500"
    : isWarn
      ? "bg-amber-500"
      : "bg-emerald-500";

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-800">{label}</span>
        <span className="text-xs text-slate-600">
          {dimension.used.toLocaleString("vi-VN")} /{" "}
          {dimension.limit.toLocaleString("vi-VN")} token (
          {pct.toFixed(1)}%)
        </span>
      </div>
      <div
        className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={`h-full ${barClass}`} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

// ---------- History strip ------------------------------------------------

function HistoryStrip({ history }: { history: CodeguardQuotaHistory }) {
  // Build N month buckets even when the API omitted months with no
  // usage. The page promises "3 tháng gần nhất" — rendering only the
  // months that have rows would silently shrink the strip to 1-2 bars
  // for low-traffic orgs, which is visually misleading ("are we
  // missing data?"). Filling zeros makes the absence visible.
  const buckets = fillMonths(history.history, history.months);

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white p-6"
      aria-labelledby="quota-history-heading"
    >
      <h3
        id="quota-history-heading"
        className="text-lg font-semibold text-slate-900"
      >
        {history.months} tháng gần nhất
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        Mỗi cột là một tháng; cao hơn = dùng nhiều hơn. Tỉ lệ với hạn mức
        hiện tại.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
        <HistoryBars
          dimensionLabel="Input"
          buckets={buckets}
          dimension="input"
          limit={history.input_limit}
        />
        <HistoryBars
          dimensionLabel="Output"
          buckets={buckets}
          dimension="output"
          limit={history.output_limit}
        />
      </div>
    </section>
  );
}

function HistoryBars({
  dimensionLabel,
  buckets,
  dimension,
  limit,
}: {
  dimensionLabel: string;
  buckets: QuotaHistoryEntry[];
  dimension: "input" | "output";
  limit: number | null;
}) {
  // Y-axis: scale to whichever is larger — the configured cap or the
  // historical max. Without this max(), an org that briefly went over
  // their cap (or had it lowered after the spend) would render bars
  // clipped at 100% with the actual spend invisible.
  const tokenKey = dimension === "input" ? "input_tokens" : "output_tokens";
  const histMax = Math.max(0, ...buckets.map((b) => b[tokenKey] as number));
  const yMax = Math.max(limit ?? 0, histMax, 1); // never divide by zero

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between text-xs text-slate-500">
        <span className="font-medium text-slate-800">{dimensionLabel}</span>
        <span>
          {limit !== null
            ? `Hạn mức: ${limit.toLocaleString("vi-VN")} token`
            : "Không giới hạn"}
        </span>
      </div>
      <div
        className="flex h-32 items-end gap-2"
        role="img"
        aria-label={`Biểu đồ ${dimensionLabel.toLowerCase()} ${buckets.length} tháng gần nhất`}
      >
        {buckets.map((b) => {
          const used = b[tokenKey] as number;
          const heightPct = (used / yMax) * 100;
          return (
            <div key={b.period_start} className="flex flex-1 flex-col items-center gap-1">
              <div
                className="w-full rounded-t bg-blue-500"
                style={{ height: `${Math.max(2, heightPct)}%` }}
                title={`${used.toLocaleString("vi-VN")} token (${formatDateVi(
                  b.period_start,
                )})`}
              />
              <span className="text-[10px] text-slate-500">
                {formatMonthShort(b.period_start)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- helpers ------------------------------------------------------

/** Days remaining until the next month's first day in UTC. The cap
 *  resets at the start of the calendar month UTC-side (matches
 *  `date_trunc('month', NOW())` in the SQL); compute the countdown
 *  in the same frame so admins in UTC+12 don't see a "0 days" lie. */
function daysUntilNextMonth(periodStartIso: string | null): number {
  // No period_start → we don't have a reference frame, so render 0
  // (which the page treats as "no countdown to show"). Prefer that
  // over guessing — a fabricated countdown could mislead planning.
  if (!periodStartIso) return 0;
  const now = new Date();
  const nextMonth = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth() + 1,
    1,
    0,
    0,
    0,
    0,
  );
  const diffMs = nextMonth - now.getTime();
  return Math.max(0, Math.ceil(diffMs / (24 * 60 * 60 * 1000)));
}

/** Format an ISO date as `dd/MM/yyyy` (vi-VN convention). */
function formatDateVi(iso: string): string {
  // Avoid `new Date(iso)` for date-only strings — the JS engine may
  // interpret it as UTC, which can shift to the previous day in
  // negative-offset timezones. Parse the parts directly.
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

/** Format an ISO date as a short Vietnamese month label (e.g. "T5/26"). */
function formatMonthShort(iso: string): string {
  // `noUncheckedIndexedAccess` is on in tsconfig — destructured tuple
  // elements are typed `string | undefined`. Default to empty strings
  // so a malformed ISO doesn't crash the whole strip; the worst case
  // is a label that reads "T0/" which makes the parse failure visible.
  const parts = iso.slice(0, 10).split("-");
  const y = parts[0] ?? "";
  const m = parts[1] ?? "";
  return `T${parseInt(m, 10)}/${y.slice(2)}`;
}

/** Fill N most-recent months with zero-rows for any month the API
 *  omitted (org made zero requests that month). Returns most-recent
 *  first to mirror the API contract; HistoryBars reverses for display
 *  so left-to-right reads chronologically.  */
function fillMonths(
  rows: QuotaHistoryEntry[],
  n: number,
): QuotaHistoryEntry[] {
  const byKey = new Map<string, QuotaHistoryEntry>();
  for (const r of rows) byKey.set(r.period_start.slice(0, 10), r);

  const now = new Date();
  const out: QuotaHistoryEntry[] = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1));
    const iso = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(
      2,
      "0",
    )}-01`;
    const existing = byKey.get(iso);
    out.push(
      existing ?? {
        period_start: iso,
        input_tokens: 0,
        output_tokens: 0,
      },
    );
  }
  // Reverse for left-to-right chronological display.
  return out.reverse();
}
