"use client";

/**
 * Tenant-facing audit log for codeguard quota mutations.
 *
 * Reads `codeguard_quota_audit_log` scoped to the caller's org via
 * the new `GET /api/v1/codeguard/quota/audit` route. Closes a real
 * tenant ops loop: pre-this-page the only way for a tenant admin to
 * answer "who on our team raised our cap last week" was to file a
 * support ticket — the data was already in the audit table (set + reset
 * mutations land an audit row in the same transaction since migration
 * 0026), it just had no UI surface.
 *
 * Filters mirror the CLI's `audit` subcommand:
 *   * `since` — ISO date (`YYYY-MM-DD`), inclusive lower bound
 *   * `action` — restrict to one of {quota_set, quota_reset}
 *   * `limit` — capped server-side at 200; default 50
 *
 * Read-only: there's no UI for ops mutations here (raise/reset).
 * Those stay CLI-only because they're operational, not tenant-self-
 * serve. The audit page just exposes the historical record.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Download, Filter, Loader2, AlertTriangle } from "lucide-react";

import {
  useCodeguardQuotaAudit,
  type CodeguardQuotaAudit,
  type QuotaAuditEntry,
  type QuotaAuditFilters,
} from "@/hooks/codeguard";

const ACTION_OPTIONS: Array<{ value: QuotaAuditFilters["action"] | undefined; label: string }> = [
  { value: undefined, label: "Tất cả hành động" },
  { value: "quota_set", label: "Đặt hạn mức (set)" },
  { value: "quota_reset", label: "Reset usage (reset)" },
  // `quota_reconcile` rows are emitted by the reconcile cron's
  // `--remediate` path (see scripts/codeguard_quotas.py). An admin
  // investigating a cap-cache realignment ("why did our usage row
  // suddenly drop without anyone running reset?") needs a filter
  // chip — without it they'd have to URL-edit the query param by
  // hand, which is a poor user experience for a routine ops drill-
  // down.
  { value: "quota_reconcile", label: "Đồng bộ hạn mức (reconcile)" },
];

export default function CodeguardQuotaAuditPage() {
  const [action, setAction] = useState<QuotaAuditFilters["action"] | undefined>(undefined);
  const [since, setSince] = useState<string>("");
  // Pages accumulate as `pages` — each entry is one server response.
  // The flat `entries` view is built by concatenating every page's
  // entries. When filters change we reset to a fresh first page;
  // when the user clicks "Tải thêm" we append the next page's
  // request via the latest `next_cursor`.
  const [pages, setPages] = useState<CodeguardQuotaAudit[]>([]);
  const [cursor, setCursor] = useState<string | undefined>(undefined);

  // Compose filters; empty `since` becomes undefined so the URL doesn't
  // carry `since=` (which the server would treat as a malformed date).
  const filters: QuotaAuditFilters = {
    limit: 100,
    action,
    since: since || undefined,
    before: cursor,
  };
  const { data, isLoading, isError } = useCodeguardQuotaAudit(filters);

  // Reset pagination when filters change. Without this, pressing
  // "Tải thêm" once and then changing `action` would mix old-filter
  // entries into the new-filter view. We watch `(action, since)` —
  // not `cursor` — so user-driven cursor changes don't reset.
  useEffect(() => {
    setPages([]);
    setCursor(undefined);
  }, [action, since]);

  // Accumulate page responses into `pages`. We track by cursor so
  // the same page-1 response on initial load doesn't get duplicated
  // by re-renders (TanStack Query may return the same data object
  // multiple times during transitions).
  useEffect(() => {
    if (!data) return;
    setPages((prev) => {
      // Already accumulated this exact cursor's response? Skip.
      const lastEntry = prev.length > 0 ? prev[prev.length - 1] : null;
      const lastEntryFirstId =
        lastEntry && lastEntry.entries[0] ? lastEntry.entries[0].id : null;
      const dataFirstId = data.entries[0] ? data.entries[0].id : null;
      if (lastEntry && lastEntryFirstId === dataFirstId) return prev;
      return [...prev, data];
    });
  }, [data]);

  const allEntries: QuotaAuditEntry[] = pages.flatMap((p) => p.entries);
  // The page can fetch more when the most recent response carried a
  // next_cursor. Clicking the button stages that cursor; the hook
  // re-runs the query, and the effect above appends the new page.
  // tsconfig has `noUncheckedIndexedAccess` so `pages[i]` is typed
  // `T | undefined` even after a length check; the explicit
  // `?? null` collapses that into the same shape as the API field.
  const latestNextCursor =
    pages.length > 0 ? (pages[pages.length - 1]?.next_cursor ?? null) : null;

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Nhật ký hạn mức</h2>
          <p className="text-sm text-slate-600">
            Mọi thay đổi hạn mức (set, reset) trong tổ chức của bạn — append-only,
            không thể chỉnh sửa.
          </p>
        </div>
        <Link
          href="/codeguard/quota"
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
        >
          <ArrowLeft size={14} /> Quay lại trang hạn mức
        </Link>
      </header>

      {/* ---------- Filter bar ---------- */}
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
          <Filter size={12} /> Bộ lọc
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col text-xs">
            <span className="mb-1 text-slate-600">Hành động</span>
            <select
              value={action ?? ""}
              onChange={(e) => setAction((e.target.value || undefined) as typeof action)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {ACTION_OPTIONS.map((o) => (
                <option key={o.label} value={o.value ?? ""}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs">
            <span className="mb-1 text-slate-600">Từ ngày</span>
            <input
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            />
          </label>
          {since && (
            // Quick-clear so the user doesn't have to manually delete
            // the input. Keeps the picker easy to clear vs cumbersome.
            <button
              type="button"
              onClick={() => setSince("")}
              className="rounded-md border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              Xoá lọc ngày
            </button>
          )}
          {/* CSV download — respects the current filters via the same
              query params the table uses, so what the user sees is what
              they get. The browser's built-in download flow handles
              the streaming response from the server (route returns
              Content-Disposition: attachment with a date-stamped
              filename). Compliance use case: send this to an auditor. */}
          <a
            href={buildCsvUrl(filters)}
            download
            className="ml-auto inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            <Download size={12} /> Tải CSV
          </a>
        </div>
      </section>

      {/* ---------- Body ---------- */}
      {isLoading && pages.length === 0 ? (
        // Initial-load spinner. Subsequent pages show their own
        // inline spinner on the "Tải thêm" button instead of
        // replacing the table with a full-page loader.
        <div
          className="flex items-center gap-2 text-sm text-slate-600"
          role="status"
          aria-live="polite"
        >
          <Loader2 size={16} className="animate-spin" /> Đang tải nhật ký…
        </div>
      ) : isError && pages.length === 0 ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          <AlertTriangle size={16} className="mr-2 inline-block text-red-700" />
          Lỗi khi tải nhật ký. Thử lại sau ít phút.
        </div>
      ) : allEntries.length === 0 ? (
        // Distinct empty state — distinguishes "no events match the
        // filter" from "no events at all" only when filters are set.
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-600">
          {action || since
            ? "Không có sự kiện nào khớp với bộ lọc."
            : "Tổ chức của bạn chưa có thay đổi hạn mức nào được ghi nhận."}
        </div>
      ) : (
        <>
          <AuditTable entries={allEntries} />
          {/* Load-more footer. Only renders when the latest page
              carried a next_cursor — null cursor means we've reached
              the end and clicking would just re-fetch the same data.
              Disable the button while a fetch is in-flight to
              prevent double-clicking from duplicating the page. */}
          {latestNextCursor && (
            <div className="flex items-center justify-center pt-2">
              <button
                type="button"
                onClick={() => setCursor(latestNextCursor)}
                disabled={isLoading}
                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {isLoading ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 size={14} className="animate-spin" /> Đang tải…
                  </span>
                ) : (
                  `Tải thêm (đã hiển thị ${allEntries.length})`
                )}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------- Table ------------------------------------------------------

function AuditTable({ entries }: { entries: QuotaAuditEntry[] }) {
  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">Thời điểm</th>
            <th className="px-4 py-3">Người thực hiện</th>
            <th className="px-4 py-3">Hành động</th>
            <th className="px-4 py-3">Tóm tắt</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {entries.map((e) => (
            <tr key={e.id}>
              <td className="px-4 py-2 align-top text-xs tabular-nums text-slate-700">
                {formatOccurredAt(e.occurred_at)}
              </td>
              <td className="px-4 py-2 align-top text-sm text-slate-900">
                {/* `actor` is free-text — could be `alice`, an OS
                    username, or a service-account marker like
                    `oncall-billing-${TICKET}`. Render verbatim so
                    operators can grep their ticketing tool by it. */}
                {e.actor ?? <span className="text-slate-400">—</span>}
              </td>
              <td className="px-4 py-2 align-top">
                <ActionBadge action={e.action} />
              </td>
              <td className="px-4 py-2 align-top text-xs text-slate-700">
                {/* Pre-rendered server-side with vi-VN dot grouping.
                    The frontend doesn't re-implement the diff format
                    — same source-of-truth as the CLI's `audit`
                    subcommand, no risk of drift. */}
                {e.summary}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ActionBadge({ action }: { action: string | null }) {
  // Color band by action:
  //   - `quota_set` (blue, neutral) — cap-change path
  //   - `quota_reset` (amber, attention) — destructive zeroing path
  //   - `quota_reconcile` (slate, system-toned) — automated cron
  //     remediation, distinct from human admin actions because the
  //     ops engineer reading this row wants to see at a glance
  //     "this was a reconcile, not someone editing a cap"
  // Unknown actions render as plain text with no badge — the API
  // rejects unknown filter values, but a future action that lands
  // without UI work shouldn't crash the page either.
  if (action === "quota_set") {
    return (
      <span className="inline-flex rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-800">
        quota_set
      </span>
    );
  }
  if (action === "quota_reset") {
    return (
      <span className="inline-flex rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
        quota_reset
      </span>
    );
  }
  if (action === "quota_reconcile") {
    return (
      <span className="inline-flex rounded-md border border-slate-300 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
        quota_reconcile
      </span>
    );
  }
  return <span className="text-xs text-slate-600">{action ?? "—"}</span>;
}

/** Format an ISO timestamp as `dd/MM/yyyy HH:mm` — vi-VN convention,
 *  short enough to fit in a column without wrapping. Times in UTC are
 *  rendered in the user's local timezone via `Date` parsing; this
 *  matches what an operator would see on their watch. */
function formatOccurredAt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso; // malformed — show raw rather than crash
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
}

/** Build the CSV-export URL with the active filters baked in. Uses
 *  `?format=csv` rather than a separate `/audit.csv` endpoint so the
 *  filter logic lives in one place server-side.
 *
 *  Note: this URL doesn't include the auth headers (`Authorization`,
 *  `X-Org-ID`) that `apiFetch` adds — the browser's `download`
 *  attribute fires a fresh GET that inherits the user's session
 *  cookie / auth state from whatever the dashboard relies on (in
 *  practice: Supabase auth carries via cookies). If a future deploy
 *  switches to bearer-only auth, this CTA needs a fetch-then-blob
 *  refactor — flagged in the codeguard ops runbook §15. */
function buildCsvUrl(filters: { action?: string; since?: string }): string {
  const params = new URLSearchParams();
  params.set("format", "csv");
  if (filters.action) params.set("action", filters.action);
  if (filters.since) params.set("since", filters.since);
  return `/api/v1/codeguard/quota/audit?${params.toString()}`;
}
