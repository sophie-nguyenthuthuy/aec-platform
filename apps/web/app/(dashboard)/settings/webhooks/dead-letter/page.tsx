"use client";

/**
 * Dead-letter dashboard for webhook deliveries.
 *
 * Lists `webhook_deliveries` rows with `status='failed'` across every
 * subscription in the caller's org. Failed = the dispatcher exhausted
 * its 6 retries (~14 hours of backoff). Without this page, an admin
 * would have to query the DB directly to see them, or drill per-
 * subscription via `/settings/webhooks/[id]` (which only shows that
 * one's failures).
 *
 * Each row has a "Retry" action that calls the existing
 * `POST /webhooks/deliveries/{id}/redeliver` endpoint — inserts a
 * fresh `pending` row with a new id (which doubles as the receiver's
 * idempotency key) so the receiver can dedupe on retry.
 */

import Link from "next/link";
import { useState } from "react";

import {
  type WebhookDelivery,
  useDeadLetterDeliveries,
  useRedeliverFromDeadLetter,
} from "@/hooks/webhooks";
import { useSession } from "@/lib/auth-context";


export default function WebhooksDeadLetterPage(): JSX.Element {
  const session = useSession();
  const isAdmin = session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const [windowDays, setWindowDays] = useState(7);
  const deliveries = useDeadLetterDeliveries({ since_days: windowDays, limit: 100 });

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Trang này chỉ dành cho admin.
        </div>
      </div>
    );
  }

  const WINDOW_OPTIONS = [
    { days: 1, label: "1 ngày" },
    { days: 7, label: "7 ngày" },
    { days: 30, label: "30 ngày" },
  ];

  const rows = deliveries.data ?? [];

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Webhook dead-letter</h1>
          <p className="text-sm text-slate-500">
            Webhook đã hết số lần thử (6 lần, ~14 giờ backoff). Bấm{" "}
            <strong>Thử lại</strong> để tạo bản gửi mới — bản cũ vẫn được giữ làm bản ghi.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link
            href="/settings/webhooks"
            className="text-slate-700 underline hover:text-slate-900"
          >
            ← Quay lại danh sách webhook
          </Link>
          <div className="flex gap-1">
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
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
            Đã thất bại vĩnh viễn
          </h2>
          <p className="text-xs text-slate-500">
            {rows.length} bản gửi {rows.length === 100 ? "(giới hạn 100 — thu hẹp khoảng thời gian để xem cũ hơn)" : ""}
          </p>
        </header>

        {deliveries.isLoading ? (
          <div className="px-4 py-6 text-sm text-slate-500">Đang tải…</div>
        ) : deliveries.isError ? (
          <div className="px-4 py-6 text-sm text-red-700">
            Không thể tải dead-letter: {(deliveries.error as Error)?.message ?? "lỗi không xác định"}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-slate-500">
            🎉 Không có webhook nào thất bại trong {windowDays} ngày qua.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2">Thời điểm</th>
                <th className="px-3 py-2">Sự kiện</th>
                <th className="px-3 py-2">Subscription</th>
                <th className="px-3 py-2 text-right">Số lần thử</th>
                <th className="px-3 py-2">Lỗi</th>
                <th className="px-3 py-2 text-right">Hành động</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <DeadLetterRow key={d.id} delivery={d} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}


function DeadLetterRow({ delivery }: { delivery: WebhookDelivery }): JSX.Element {
  const redeliver = useRedeliverFromDeadLetter();
  const [hasRetried, setHasRetried] = useState(false);

  // Compose the inline failure message: HTTP status + error message
  // capped (some receiver bodies are kilobytes). Either / both can be
  // null when transport failed before a status came back.
  const httpStatus = delivery.response_status;
  const errorPreview = (delivery.error_message ?? "").slice(0, 160);

  return (
    <tr className="border-t border-slate-100">
      <td className="px-3 py-2 text-xs text-slate-700">
        {new Date(delivery.created_at).toLocaleString("vi-VN")}
      </td>
      <td className="px-3 py-2 font-mono text-xs text-slate-700">{delivery.event_type}</td>
      <td className="px-3 py-2">
        <Link
          href={`/settings/webhooks/${delivery.subscription_id}`}
          className="font-mono text-xs text-slate-600 underline hover:text-slate-900"
        >
          {delivery.subscription_id.slice(0, 8)}…
        </Link>
      </td>
      <td className="px-3 py-2 text-right text-xs text-slate-700">
        {delivery.attempt_count}
      </td>
      <td className="px-3 py-2 text-xs">
        {httpStatus !== null ? (
          <div className="font-mono text-rose-700">HTTP {httpStatus}</div>
        ) : null}
        {errorPreview ? (
          <div className="truncate text-slate-500">{errorPreview}</div>
        ) : null}
      </td>
      <td className="px-3 py-2 text-right">
        {hasRetried ? (
          <span className="text-xs text-emerald-700">✓ Đã xếp hàng</span>
        ) : (
          <button
            type="button"
            disabled={redeliver.isPending}
            onClick={() => {
              redeliver.mutate(delivery.id, { onSuccess: () => setHasRetried(true) });
            }}
            className="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            {redeliver.isPending ? "Đang gửi…" : "Thử lại"}
          </button>
        )}
      </td>
    </tr>
  );
}
