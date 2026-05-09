"use client";

import { use, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  RefreshCw,
  ShieldAlert,
  XCircle,
} from "lucide-react";

import {
  type DeliveriesFilters,
  type DeliveriesHistogramBucket,
  type WebhookDelivery,
  useDeliveriesHistogram,
  useRedeliverWebhook,
  useWebhookDeliveries,
  useWebhooks,
} from "@/hooks/webhooks";


/**
 * Webhook subscription detail — histogram + recent deliveries +
 * redeliver action. Counterpart to `/settings/webhooks` (list view).
 *
 * Routes here from list-row click. Backend endpoints used:
 *   GET  /webhooks/{id}/deliveries?status=...&since_days=...
 *   GET  /webhooks/{id}/deliveries/histogram?days=...
 *   POST /webhooks/deliveries/{id}/redeliver
 */
export default function WebhookDetailPage(
  { params }: { params: Promise<{ id: string }> },
) {
  // Next.js 15 makes params async; `use(...)` unwraps the promise in
  // a client component without converting the whole tree to a Server
  // Component.
  const { id } = use(params);

  const [statusFilter, setStatusFilter] = useState<DeliveriesFilters["status"]>();
  const [sinceDays, setSinceDays] = useState(7);

  const subs = useWebhooks();
  const sub = subs.data?.find((s) => s.id === id);

  const histogram = useDeliveriesHistogram(id, sinceDays);
  const deliveries = useWebhookDeliveries(id, {
    status: statusFilter,
    since_days: sinceDays,
    limit: 100,
  });

  return (
    <div className="space-y-6">
      <Link
        href="/settings/webhooks"
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft size={12} />
        Quay lại danh sách
      </Link>

      <div>
        <h2 className="text-2xl font-bold text-slate-900">
          {sub?.url ?? "Webhook"}
        </h2>
        <p className="text-sm text-slate-600">
          Lịch sử giao hàng + redeliver. Khi receiver lỗi 5xx, retry tự động
          với backoff (1m → 5m → 30m → 2h → 12h, 6 lần). Sau đó status =
          <code className="mx-1 rounded bg-slate-100 px-1">failed</code>; có
          thể redeliver thủ công bằng nút bên dưới.
        </p>
        {sub && !sub.enabled && (
          <p className="mt-2 inline-block rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">
            Subscription này đã <strong>bị tắt</strong> — deliveries pending
            sẽ không fire. Bật lại tại trang danh sách.
          </p>
        )}
      </div>

      {/* ---------- Window toggle ---------- */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Cửa sổ
        </span>
        {[1, 7, 30].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setSinceDays(d)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              sinceDays === d
                ? "bg-blue-600 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      {/* ---------- Histogram ---------- */}
      <Histogram
        buckets={histogram.data ?? []}
        loading={histogram.isLoading}
      />

      {/* ---------- Status filter chips ---------- */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Trạng thái
        </span>
        {[undefined, "delivered", "failed", "pending"].map((s) => (
          <button
            key={s ?? "all"}
            type="button"
            onClick={() => setStatusFilter(s as DeliveriesFilters["status"])}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              statusFilter === s
                ? "bg-blue-600 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {s ?? "Tất cả"}
          </button>
        ))}
      </div>

      {/* ---------- Deliveries table ---------- */}
      {deliveries.isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : deliveries.isError ? (
        <ErrorPanel error={deliveries.error as Error | null} />
      ) : !deliveries.data || deliveries.data.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
          Không có delivery nào trong cửa sổ này
          {statusFilter ? ` với trạng thái ${statusFilter}` : ""}.
        </p>
      ) : (
        <div className="space-y-2">
          {deliveries.data.map((d) => (
            <DeliveryRow key={d.id} delivery={d} subscriptionId={id} />
          ))}
        </div>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function Histogram({
  buckets,
  loading,
}: {
  buckets: DeliveriesHistogramBucket[];
  loading: boolean;
}) {
  if (loading) {
    return <div className="h-32 animate-pulse rounded-xl bg-slate-100" />;
  }
  if (buckets.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-xs text-slate-500">
        Chưa có delivery nào trong cửa sổ này.
      </div>
    );
  }
  // Bar height = max(delivered+failed+pending) across buckets so the
  // tallest day fills the chart. Failed segments stack on top of
  // delivered to make spike-vs-baseline relationships visible.
  const max = buckets.reduce(
    (m, b) => Math.max(m, b.delivered + b.failed + b.pending),
    1,
  );
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-end gap-1.5" style={{ height: 120 }}>
        {buckets.map((b) => {
          const total = b.delivered + b.failed + b.pending;
          const heightPct = (total / max) * 100;
          const dPct = total > 0 ? (b.delivered / total) * 100 : 0;
          const fPct = total > 0 ? (b.failed / total) * 100 : 0;
          return (
            <div
              key={b.day}
              className="group relative flex-1"
              title={`${b.day.slice(0, 10)} · ${b.delivered} delivered, ${b.failed} failed, ${b.pending} pending`}
            >
              <div
                className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                style={{ height: `${heightPct}%` }}
              >
                <div
                  className="bg-emerald-500"
                  style={{ height: `${dPct}%` }}
                />
                <div
                  className="bg-rose-500"
                  style={{ height: `${fPct}%` }}
                />
                <div className="bg-amber-300" style={{ flex: 1 }} />
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center justify-center gap-4 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-emerald-500" /> delivered
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-rose-500" /> failed
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-amber-300" /> pending
        </span>
      </div>
    </div>
  );
}


function DeliveryRow({
  delivery,
  subscriptionId,
}: {
  delivery: WebhookDelivery;
  subscriptionId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const redeliver = useRedeliverWebhook(subscriptionId);
  const [redelivered, setRedelivered] = useState(false);

  const tone =
    delivery.status === "delivered"
      ? "border-emerald-200 bg-emerald-50/40"
      : delivery.status === "failed"
        ? "border-rose-200 bg-rose-50/40"
        : "border-amber-200 bg-amber-50/40";

  return (
    <div className={`rounded-lg border ${tone}`}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span className="shrink-0 text-slate-400">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <StatusBadge status={delivery.status} />
        <span className="flex-1 truncate font-mono text-xs text-slate-700">
          {delivery.event_type}
        </span>
        <span className="shrink-0 text-[11px] tabular-nums text-slate-500">
          attempt {delivery.attempt_count}
          {delivery.response_status && ` · HTTP ${delivery.response_status}`}
        </span>
        <span className="shrink-0 text-[11px] text-slate-400">
          {new Date(delivery.created_at).toLocaleString("vi-VN", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-slate-100 px-4 py-3">
          {delivery.error_message && (
            <p className="text-xs text-rose-700">
              <strong>Error:</strong> {delivery.error_message}
            </p>
          )}
          {delivery.response_body_snippet && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Response body
              </p>
              <pre className="mt-1 overflow-x-auto rounded bg-slate-900 px-3 py-2 text-[11px] text-slate-100">
                {delivery.response_body_snippet}
              </pre>
            </div>
          )}
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Payload
            </p>
            <pre className="mt-1 overflow-x-auto rounded bg-slate-900 px-3 py-2 text-[11px] text-slate-100">
              {JSON.stringify(delivery.payload, null, 2)}
            </pre>
          </div>

          {/* Redeliver only makes sense for failed rows; pending will
              be picked up by the cron tick anyway, and delivered
              would create a duplicate effect on the receiver. */}
          {delivery.status === "failed" && (
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                onClick={() =>
                  redeliver.mutate(delivery.id, {
                    onSuccess: () => setRedelivered(true),
                  })
                }
                disabled={redeliver.isPending || redelivered}
                className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
              >
                {redeliver.isPending ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <RefreshCw size={12} />
                )}
                {redelivered ? "Đã enqueue lại" : "Redeliver"}
              </button>
              {redelivered && (
                <span className="text-[11px] text-emerald-700">
                  Enqueue thành công — cron sẽ xử lý trong vòng 1 phút.
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function StatusBadge({ status }: { status: WebhookDelivery["status"] }) {
  const meta: Record<
    WebhookDelivery["status"],
    { label: string; tone: string; icon: React.ReactNode }
  > = {
    delivered: {
      label: "delivered",
      tone: "bg-emerald-100 text-emerald-800",
      icon: <CheckCircle2 size={11} />,
    },
    failed: {
      label: "failed",
      tone: "bg-rose-100 text-rose-800",
      icon: <XCircle size={11} />,
    },
    pending: {
      label: "pending",
      tone: "bg-amber-100 text-amber-800",
      icon: <Clock size={11} />,
    },
    in_flight: {
      label: "in_flight",
      tone: "bg-blue-100 text-blue-800",
      icon: <Loader2 size={11} className="animate-spin" />,
    },
  };
  const m = meta[status];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${m.tone}`}
    >
      {m.icon} {m.label}
    </span>
  );
}


function ErrorPanel({ error }: { error: Error | null }) {
  const msg = error?.message ?? "";
  const isForbidden = msg.includes("403") || /forbidden/i.test(msg);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {isForbidden ? (
        <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      ) : (
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      )}
      <p>
        {isForbidden
          ? "Bạn cần quyền admin để xem trang này."
          : msg || "Không thể tải lịch sử delivery."}
      </p>
    </div>
  );
}
