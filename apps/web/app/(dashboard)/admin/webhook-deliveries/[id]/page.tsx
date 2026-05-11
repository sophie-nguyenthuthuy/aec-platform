"use client";

/**
 * Drilldown for one webhook delivery — `/admin/webhook-deliveries/[id]`.
 *
 * Lands here from a row click on the parent list page. Shows the
 * forensic detail an admin needs to answer "why did this delivery
 * fail?":
 *
 *   * Status + attempt count (current state of the row)
 *   * Pretty-printed payload (what we sent the receiver)
 *   * Latest response — status code + body snippet + error message
 *   * Timeline (created_at, next_retry_at, delivered_at)
 *   * Subscription + organization IDs (mono-spaced for copy-paste)
 *
 * What it does NOT show (deliberately):
 *
 *   * Per-attempt history. The model only stores the LATEST attempt's
 *     response_status/snippet/error — adding a `webhook_delivery_attempts`
 *     side-table is its own ticket. The page renders the latest as
 *     "current attempt #N" so the admin knows there's no missing data.
 *
 *   * Re-fire button. The org-scoped `/webhooks/deliveries/{id}/redeliver`
 *     endpoint is per-org-admin, not platform-admin. Plumbing it
 *     cross-tenant from this admin page would either need a new
 *     bypass-rls path (security risk) or imply impersonation. Out of
 *     scope for v1 — admins can ask the customer's org admin to retry.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft, AlertCircle } from "lucide-react";

import { useWebhookDeliveryAdminDetail } from "@/hooks/admin";
import { useSession } from "@/lib/auth-context";


export default function WebhookDeliveryDetailPage(): JSX.Element {
  const session = useSession();
  const params = useParams();
  const id = typeof params?.id === "string" ? params.id : undefined;

  const isAdmin =
    session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const { data, isLoading, isError, error } = useWebhookDeliveryAdminDetail(id);

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
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <Link
        href="/admin/webhook-deliveries"
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
      >
        <ChevronLeft size={14} />
        Quay lại danh sách
      </Link>

      {isLoading && (
        <p className="text-sm text-slate-500">Đang tải...</p>
      )}

      {isError && (
        <ErrorBanner error={error as Error | null} />
      )}

      {data && (
        <>
          <header className="space-y-2">
            <h1 className="font-mono text-xl font-semibold text-slate-900">
              {data.event_type}
            </h1>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <StatusPill status={data.status} />
              <span>·</span>
              <span>
                Attempt {data.attempt_count}
                {data.attempt_count > 0 && data.status === "failed" && " (final)"}
              </span>
              <span>·</span>
              <span className="font-mono">{data.id}</span>
            </div>
          </header>

          {/* ---------- Latest response / error ---------- */}
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Latest response
            </h2>
            {data.response_status === null && data.error_message === null ? (
              <p className="mt-2 text-xs text-slate-500">
                Chưa có response — request có thể chưa được dispatch (đang
                pending) hoặc thất bại trước khi receiver kịp trả.
              </p>
            ) : (
              <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                    HTTP status
                  </dt>
                  <dd className="mt-1 font-mono text-base text-slate-900">
                    {data.response_status ?? <span className="text-slate-400">—</span>}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                    Error
                  </dt>
                  <dd className="mt-1 text-xs text-rose-700">
                    {data.error_message ?? (
                      <span className="text-slate-400">—</span>
                    )}
                  </dd>
                </div>
                {data.response_body_snippet && (
                  <div className="sm:col-span-2">
                    <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                      Response body (snippet)
                    </dt>
                    <dd className="mt-1">
                      <pre className="overflow-x-auto rounded bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-700">
                        {data.response_body_snippet}
                      </pre>
                    </dd>
                  </div>
                )}
              </dl>
            )}
          </section>

          {/* ---------- Timeline ---------- */}
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Timeline
            </h2>
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                  Created
                </dt>
                <dd className="mt-1 text-xs text-slate-700">
                  {new Date(data.created_at).toLocaleString("vi-VN")}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                  Next retry
                </dt>
                <dd className="mt-1 text-xs text-slate-700">
                  {data.next_retry_at
                    ? new Date(data.next_retry_at).toLocaleString("vi-VN")
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                  Delivered
                </dt>
                <dd className="mt-1 text-xs text-slate-700">
                  {data.delivered_at
                    ? new Date(data.delivered_at).toLocaleString("vi-VN")
                    : "—"}
                </dd>
              </div>
            </dl>
          </section>

          {/* ---------- Payload ---------- */}
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Payload
            </h2>
            <p className="mt-1 text-[11px] text-slate-500">
              Body đã gửi tới receiver. Copy vào curl để replay thủ công khi
              cần.
            </p>
            <pre className="mt-3 overflow-x-auto rounded bg-slate-900 p-4 text-xs leading-relaxed text-slate-100">
              {JSON.stringify(data.payload, null, 2)}
            </pre>
          </section>

          {/* ---------- IDs ---------- */}
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Identifiers
            </h2>
            <dl className="mt-3 grid gap-3 font-mono text-xs sm:grid-cols-2">
              <div>
                <dt className="text-[11px] font-sans uppercase tracking-wide text-slate-500">
                  organization_id
                </dt>
                <dd className="mt-1 text-slate-700">{data.organization_id}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-sans uppercase tracking-wide text-slate-500">
                  subscription_id
                </dt>
                <dd className="mt-1 text-slate-700">{data.subscription_id}</dd>
              </div>
            </dl>
          </section>
        </>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function StatusPill({ status }: { status: string }) {
  // Tone matches the parent list page's StatusPill — visual idiom
  // consistency lets admins move between list and detail without
  // re-learning the colour code.
  const tone =
    status === "delivered"
      ? "bg-emerald-100 text-emerald-800"
      : status === "failed"
        ? "bg-rose-100 text-rose-800"
        : status === "in_flight"
          ? "bg-blue-100 text-blue-800"
          : "bg-slate-200 text-slate-800";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}
    >
      {status}
    </span>
  );
}


function ErrorBanner({ error }: { error: Error | null }) {
  const msg = error?.message ?? "";
  const notFound = msg.includes("404") || msg.includes("not_found");
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-medium">
          {notFound
            ? "Webhook delivery này không tồn tại"
            : "Không thể tải chi tiết delivery"}
        </p>
        <p className="mt-0.5 text-xs">
          {notFound
            ? "Có thể row đã bị retention prune (sau 30 ngày). Quay lại danh sách để chọn delivery khác."
            : msg}
        </p>
      </div>
    </div>
  );
}
