"use client";

/**
 * Admin-only dashboard for `slack_deliveries` telemetry.
 *
 * Why this dashboard exists: the drift-alert pipeline + future
 * RFQ/digest pipelines all post to a single platform Slack webhook.
 * When deliveries silently fail (Slack rate-limits us, the URL
 * rotates, the channel gets archived), the only signal today is
 * `services.slack` log warnings — easy to miss. This page surfaces
 * delivery health per `kind` (e.g. `scraper_drift`) so ops sees
 * "every alert for the last 6 hours failed with 429" before the
 * next on-call rotation does.
 *
 * Two surfaces stacked vertically:
 *
 *   1. **Per-kind summary cards** — top of the page. One card per
 *      `kind` over the configurable lookback. Card colour follows
 *      delivery rate; "no attempts in window" renders distinctly
 *      from "every attempt failed."
 *
 *   2. **Recent attempts table** — bottom. Forensic drill-down
 *      with kind + delivered filters. Shows Slack's status code
 *      and reason verbatim so an ops engineer can search for
 *      `429` / `channel_not_found` / etc.
 *
 * Server-side `require_role("admin")` gates both endpoints; the
 * page renders an "admin only" empty state for non-admins so a
 * misclick on the URL doesn't 403 with no copy.
 */

import { useTranslations } from "next-intl";
import { useState } from "react";

import {
  type SlackDeliveriesSummaryRow,
  type SlackDeliveryRow,
  useSlackDeliveries,
  useSlackDeliveriesSummary,
} from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


// Window options localised — keys mirror the `admin_slack_deliveries`
// translation namespace's `window_*` keys (parallel to the same shape
// in `admin_scrapers` so the visual idiom carries across both pages).
const WINDOW_OPTIONS: Array<{ days: number; key: "window_1" | "window_7" | "window_30" }> = [
  { days: 1, key: "window_1" },
  { days: 7, key: "window_7" },
  { days: 30, key: "window_30" },
];


export default function SlackDeliveriesDashboardPage(): JSX.Element {
  // Translation namespace — the key set is paralleled in
  // `vi/en.json` (still TBD if those keys ship; the page falls
  // back to the literal keys if a locale is missing entries).
  const t = useTranslations("admin_slack_deliveries");
  const session = useSession();
  const isAdmin = session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const [windowDays, setWindowDays] = useState(7);
  // The "show only failures" toggle defaults OFF so first-paint
  // shows the full picture (a healthy run-rate is also useful
  // information). Ops can flip it when triaging a known issue.
  const [failuresOnly, setFailuresOnly] = useState(false);

  const summary = useSlackDeliveriesSummary(windowDays);
  const deliveries = useSlackDeliveries({
    delivered: failuresOnly ? false : undefined,
    limit: 50,
  });

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          {t("non_admin_message")}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t("title")}</h1>
          <p className="text-sm text-slate-500">{t("description")}</p>
        </div>
        <div className="flex gap-1 text-xs">
          {WINDOW_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              type="button"
              onClick={() => setWindowDays(opt.days)}
              className={`rounded-full border px-3 py-1 ${
                windowDays === opt.days
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-100"
              }`}
            >
              {t(opt.key)}
            </button>
          ))}
        </div>
      </header>

      <SummaryCards
        summary={summary.data ?? []}
        isLoading={summary.isLoading}
        t={t}
      />

      <DeliveriesTable
        deliveries={deliveries.data ?? []}
        isLoading={deliveries.isLoading}
        failuresOnly={failuresOnly}
        onToggleFailuresOnly={() => setFailuresOnly((prev) => !prev)}
        t={t}
      />
    </div>
  );
}


function SummaryCards({
  summary,
  isLoading,
  t,
}: {
  summary: SlackDeliveriesSummaryRow[];
  isLoading: boolean;
  t: ReturnType<typeof useTranslations<"admin_slack_deliveries">>;
}): JSX.Element {
  if (isLoading) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        {t("loading")}
      </section>
    );
  }
  if (summary.length === 0) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">
        {t("empty_state")}
      </section>
    );
  }

  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {summary.map((row) => (
        <SummaryCard key={row.kind} row={row} t={t} />
      ))}
    </section>
  );
}


function SummaryCard({
  row,
  t,
}: {
  row: SlackDeliveriesSummaryRow;
  t: ReturnType<typeof useTranslations<"admin_slack_deliveries">>;
}): JSX.Element {
  // Card border colour encodes severity at a glance:
  //   * red    — every attempt in window failed (page someone)
  //   * amber  — at least one failure (worth a look)
  //   * grey   — no attempts in window (no data)
  //   * green  — all delivered
  const tone =
    row.delivered_rate === null
      ? "grey"
      : row.delivered_rate === 0
        ? "red"
        : row.failed_count > 0
          ? "amber"
          : "green";

  const toneClasses = {
    red: "border-red-300 bg-red-50",
    amber: "border-amber-300 bg-amber-50",
    grey: "border-slate-200 bg-slate-50",
    green: "border-emerald-200 bg-white",
  }[tone];

  return (
    <div className={`rounded-lg border p-4 ${toneClasses}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-mono text-sm font-semibold text-slate-900">{row.kind}</h3>
        <span className="text-xs text-slate-500">
          {row.delivered_rate === null
            ? t("no_attempts_in_window")
            : t("rate_pct", {
                pct: Math.round(row.delivered_rate * 100),
              })}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-700">
        <div>
          <div className="text-slate-500">{t("col_attempts")}</div>
          <div className="font-semibold">{row.total_attempts}</div>
        </div>
        <div>
          <div className="text-slate-500">{t("col_delivered")}</div>
          <div className="font-semibold text-emerald-700">{row.delivered_count}</div>
        </div>
        <div>
          <div className="text-slate-500">{t("col_failed")}</div>
          <div className={row.failed_count > 0 ? "font-semibold text-red-700" : "font-semibold"}>
            {row.failed_count}
          </div>
        </div>
      </div>
      {row.last_failure_at ? (
        <div className="mt-3 border-t border-slate-200 pt-2 text-xs">
          <div className="text-slate-500">{t("last_failure")}</div>
          <div className="text-slate-700">
            {new Date(row.last_failure_at).toLocaleString()}
          </div>
          {row.last_failure_reason ? (
            <div className="font-mono text-[11px] text-red-700">
              {row.last_failure_reason}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


function DeliveriesTable({
  deliveries,
  isLoading,
  failuresOnly,
  onToggleFailuresOnly,
  t,
}: {
  deliveries: SlackDeliveryRow[];
  isLoading: boolean;
  failuresOnly: boolean;
  onToggleFailuresOnly: () => void;
  t: ReturnType<typeof useTranslations<"admin_slack_deliveries">>;
}): JSX.Element {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {t("table_heading")}
        </h2>
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={failuresOnly}
            onChange={onToggleFailuresOnly}
            className="h-3.5 w-3.5"
          />
          {t("failures_only_toggle")}
        </label>
      </header>
      {isLoading ? (
        <div className="px-4 py-6 text-sm text-slate-500">{t("loading")}</div>
      ) : deliveries.length === 0 ? (
        <div className="px-4 py-6 text-sm text-slate-500">{t("table_empty")}</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">{t("col_when")}</th>
              <th className="px-3 py-2">{t("col_kind")}</th>
              <th className="px-3 py-2">{t("col_outcome")}</th>
              <th className="px-3 py-2 text-right">{t("col_status")}</th>
              <th className="px-3 py-2">{t("col_reason")}</th>
              <th className="px-3 py-2">{t("col_preview")}</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.map((d) => (
              <tr key={d.id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-2 text-xs text-slate-600">
                  {new Date(d.created_at).toLocaleString()}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-slate-700">{d.kind}</td>
                <td className="px-3 py-2">
                  {d.delivered ? (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                      {t("outcome_delivered")}
                    </span>
                  ) : (
                    <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                      {t("outcome_failed")}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  {d.status_code ?? "—"}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-slate-700">
                  {d.reason ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs text-slate-700">
                  {/* Cap the cell width to keep the row height
                      manageable; the full preview is up to 200 chars
                      and would otherwise dominate the table. */}
                  <span className="line-clamp-2 max-w-md">{d.text_preview}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
