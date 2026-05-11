"use client";

/**
 * Admin-only dashboard for cross-tenant webhook delivery telemetry.
 *
 * Why this dashboard exists: customer-facing webhooks fail silently
 * from the platform's perspective. A customer's receiver returning
 * 502 only shows up in our logs as a worker WARNING; the customer
 * doesn't know either, because we retry with backoff and they get
 * the message eventually (or don't, if we exhaust attempts). This
 * dashboard surfaces the platform-wide picture so ops can answer
 * "is webhook delivery healthy" in one glance.
 *
 * Key signal: the `distinct_orgs` count on each summary card.
 *   * `distinct_orgs > 1` AND `delivered_rate < 1` — platform-wide
 *     issue (our dispatcher, network, etc).
 *   * `distinct_orgs == 1` AND `delivered_rate < 1` — one customer's
 *     receiver is misconfigured; they should hear from support, not
 *     us being on call.
 *
 * Server-side `require_role("admin")` gates both endpoints; the
 * page renders an "admin only" empty state for non-admins so a
 * misclick on the URL doesn't 403 with no copy.
 */

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import {
  type WebhookDeliveriesAdminSummaryRow,
  type WebhookDeliveryAdminRow,
  type WebhookDeliveryStatus,
  useWebhookDeliveriesAdmin,
  useWebhookDeliveriesAdminSummary,
} from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


// Lookback window options. 1d / 7d / 30d mirrors the slack-deliveries
// dashboard for visual idiom consistency.
const WINDOW_OPTIONS: Array<{
  days: number;
  key: "window_1" | "window_7" | "window_30";
}> = [
  { days: 1, key: "window_1" },
  { days: 7, key: "window_7" },
  { days: 30, key: "window_30" },
];

// Status filter pills. The four-state machine pinned in
// `tests/test_webhook_outbox_state_machine_pin.py` AND in the
// hook's `WebhookDeliveryStatus` union. Localised labels so the
// wire literal stays in English while the UI matches the user's
// locale.
const STATUS_FILTERS: ReadonlyArray<{
  status: WebhookDeliveryStatus | "all";
  key:
    | "filter_all"
    | "filter_pending"
    | "filter_in_flight"
    | "filter_delivered"
    | "filter_failed";
}> = [
  { status: "all", key: "filter_all" },
  { status: "failed", key: "filter_failed" },
  { status: "pending", key: "filter_pending" },
  { status: "in_flight", key: "filter_in_flight" },
  { status: "delivered", key: "filter_delivered" },
];


export default function WebhookDeliveriesAdminPage(): JSX.Element {
  const t = useTranslations("admin_webhook_deliveries");
  const session = useSession();
  const isAdmin =
    session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const [windowDays, setWindowDays] = useState(7);
  const [statusFilter, setStatusFilter] = useState<
    WebhookDeliveryStatus | "all"
  >("failed"); // default to "failed" — the triage view ops opens for

  const summary = useWebhookDeliveriesAdminSummary(windowDays);
  const deliveries = useWebhookDeliveriesAdmin({
    status: statusFilter === "all" ? undefined : statusFilter,
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
        statusFilter={statusFilter}
        onStatusFilter={setStatusFilter}
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
  summary: WebhookDeliveriesAdminSummaryRow[];
  isLoading: boolean;
  t: ReturnType<typeof useTranslations<"admin_webhook_deliveries">>;
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
        <SummaryCard key={row.event_type} row={row} t={t} />
      ))}
    </section>
  );
}


function SummaryCard({
  row,
  t,
}: {
  row: WebhookDeliveriesAdminSummaryRow;
  t: ReturnType<typeof useTranslations<"admin_webhook_deliveries">>;
}): JSX.Element {
  // Card colour: same red/amber/grey/green encoding as the slack
  // dashboard so the visual idiom carries.
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

  // Discriminate platform-wide breakage from single-customer misconfig.
  // distinct_orgs > 1 means multiple tenants are seeing failures; that
  // points the finger at the dispatcher / network / our infra, not at
  // a customer's receiver.
  const isPlatformWide =
    row.distinct_orgs > 1 && row.failed_count > 0;

  return (
    <div className={`rounded-lg border p-4 ${toneClasses}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-mono text-sm font-semibold text-slate-900">
          {row.event_type}
        </h3>
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
          <div className="font-semibold text-emerald-700">
            {row.delivered_count}
          </div>
        </div>
        <div>
          <div className="text-slate-500">{t("col_failed")}</div>
          <div
            className={
              row.failed_count > 0
                ? "font-semibold text-red-700"
                : "font-semibold"
            }
          >
            {row.failed_count}
          </div>
        </div>
      </div>
      {row.pending_count > 0 ? (
        <div className="mt-2 text-xs text-amber-700">
          {t("pending_backlog", { count: row.pending_count })}
        </div>
      ) : null}
      <div className="mt-3 flex items-center justify-between border-t border-slate-200 pt-2 text-xs text-slate-700">
        <span>
          {t("distinct_orgs", { count: row.distinct_orgs })}
        </span>
        {isPlatformWide ? (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-medium text-red-800">
            {t("platform_wide_chip")}
          </span>
        ) : null}
      </div>
      {row.last_failure_at ? (
        <div className="mt-2 text-xs">
          <div className="text-slate-500">{t("last_failure")}</div>
          <div className="text-slate-700">
            {new Date(row.last_failure_at).toLocaleString()}
          </div>
          {row.last_failure_message ? (
            // Cap at 2 lines — error_message can be a stack trace
            // and we don't want one card to dominate the grid.
            <div className="line-clamp-2 font-mono text-[11px] text-red-700">
              {row.last_failure_message}
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
  statusFilter,
  onStatusFilter,
  t,
}: {
  deliveries: WebhookDeliveryAdminRow[];
  isLoading: boolean;
  statusFilter: WebhookDeliveryStatus | "all";
  onStatusFilter: (s: WebhookDeliveryStatus | "all") => void;
  t: ReturnType<typeof useTranslations<"admin_webhook_deliveries">>;
}): JSX.Element {
  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {t("table_heading")}
        </h2>
        <div className="flex flex-wrap gap-1 text-xs">
          {STATUS_FILTERS.map(({ status, key }) => (
            <button
              key={status}
              type="button"
              onClick={() => onStatusFilter(status)}
              className={`rounded-full border px-3 py-1 ${
                statusFilter === status
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-100"
              }`}
            >
              {t(key)}
            </button>
          ))}
        </div>
      </header>
      {isLoading ? (
        <div className="px-4 py-6 text-sm text-slate-500">{t("loading")}</div>
      ) : deliveries.length === 0 ? (
        <div className="px-4 py-6 text-sm text-slate-500">{t("table_empty")}</div>
      ) : (
        // Scroll-wrap the table only (not the surrounding section
        // header + filters) so on mobile the 6-column delivery table
        // scrolls horizontally within its own band rather than the
        // whole section card.
        <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">{t("col_when")}</th>
              <th className="px-3 py-2">{t("col_event_type")}</th>
              <th className="px-3 py-2">{t("col_status")}</th>
              <th className="px-3 py-2 text-right">{t("col_attempts_short")}</th>
              <th className="px-3 py-2 text-right">{t("col_response")}</th>
              <th className="px-3 py-2">{t("col_error")}</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.map((d) => (
              // Whole row is clickable → drilldown. We use a Link
              // wrapping the cell content rather than `<tr onClick>`
              // so middle-click + cmd-click open in a new tab the
              // way ops engineers expect for triage workflows.
              <tr
                key={d.id}
                className="cursor-pointer border-t border-slate-100 align-top transition hover:bg-slate-50"
              >
                <td className="px-3 py-2 text-xs text-slate-600">
                  <Link
                    href={`/admin/webhook-deliveries/${d.id}`}
                    className="block"
                  >
                    {new Date(d.created_at).toLocaleString()}
                  </Link>
                </td>
                <td className="px-3 py-2 font-mono text-xs text-slate-700">
                  <Link
                    href={`/admin/webhook-deliveries/${d.id}`}
                    className="block"
                  >
                    {d.event_type}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <StatusPill status={d.status} t={t} />
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  {d.attempt_count}
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  {d.response_status ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs text-slate-700">
                  {d.error_message ? (
                    <span className="line-clamp-2 max-w-md font-mono text-[11px] text-red-700">
                      {d.error_message}
                    </span>
                  ) : d.response_body_snippet ? (
                    <span className="line-clamp-2 max-w-md font-mono text-[11px]">
                      {d.response_body_snippet}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </section>
  );
}


function StatusPill({
  status,
  t,
}: {
  status: WebhookDeliveryStatus;
  t: ReturnType<typeof useTranslations<"admin_webhook_deliveries">>;
}): JSX.Element {
  // Per-state colour. Note: `pending` and `in_flight` are both
  // "in-progress" but distinct — pending is queued, in_flight is
  // mid-POST. The cron drain logic relies on the difference (an
  // in_flight row that's been there for >5min is a stuck dispatcher).
  const classes = {
    pending: "bg-slate-100 text-slate-700",
    in_flight: "bg-amber-100 text-amber-800",
    delivered: "bg-emerald-100 text-emerald-800",
    failed: "bg-red-100 text-red-800",
  }[status];

  const labelKey = `status_${status}` as
    | "status_pending"
    | "status_in_flight"
    | "status_delivered"
    | "status_failed";

  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {t(labelKey)}
    </span>
  );
}
