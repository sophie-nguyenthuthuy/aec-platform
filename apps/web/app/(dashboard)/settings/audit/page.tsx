"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Filter, ShieldAlert } from "lucide-react";

import { type AuditEvent, useAuditEvents } from "@/hooks/audit";


// Closed set — mirrors `services/audit.AuditAction` literal on the API.
// Keeping it client-side as a list lets us label-i18n + render a clean
// dropdown without an extra round-trip. KEEP IN SYNC with the literal:
// when adding a new audit action server-side, add it here too — otherwise
// admins can't filter to it from the dropdown even though the rows do
// land in the table.
const ACTION_FILTERS: Array<{ value: string; label: string }> = [
  { value: "",                                 label: "Tất cả hành động" },
  // CostPulse
  { value: "costpulse.estimate.approve",       label: "Duyệt dự toán" },
  { value: "costpulse.boq.import",             label: "Nhập BOQ" },
  { value: "costpulse.suppliers.import",       label: "Nhập danh sách NCC" },
  { value: "costpulse.rfq.slots_expired",      label: "RFQ hết hạn (tự động)" },
  // ProjectPulse
  { value: "pulse.change_order.approve",       label: "Duyệt change order" },
  { value: "pulse.change_order.reject",        label: "Từ chối change order" },
  // Org / RBAC
  { value: "org.member.role_change",           label: "Đổi vai trò thành viên" },
  { value: "org.member.remove",                label: "Xóa thành viên" },
  { value: "org.invitation.create",            label: "Tạo lời mời" },
  { value: "org.invitation.revoke",            label: "Thu hồi lời mời" },
  { value: "org.invitation.accept",            label: "Chấp nhận lời mời" },
  // Notifications
  { value: "notifications.preference.update",  label: "Đổi tuỳ chọn thông báo" },
  // Handover
  { value: "handover.package.deliver",         label: "Bàn giao gói" },
  // Punch list
  { value: "punchlist.list.sign_off",          label: "Ký nghiệm thu punch list" },
  // Submittals
  { value: "submittals.review.approve",        label: "Duyệt submittal" },
  { value: "submittals.review.approve_as_noted", label: "Duyệt có ghi chú" },
  { value: "submittals.review.revise_resubmit", label: "Yêu cầu nộp lại" },
  { value: "submittals.review.reject",         label: "Từ chối submittal" },
  // Cross-tenant platform admin (global config — see audit.AuditAction)
  { value: "admin.normalizer_rule.create",     label: "Tạo luật chuẩn hoá" },
  { value: "admin.normalizer_rule.update",     label: "Sửa luật chuẩn hoá" },
  { value: "admin.normalizer_rule.delete",     label: "Xoá luật chuẩn hoá" },
];

const RESOURCE_FILTERS: Array<{ value: string; label: string }> = [
  { value: "",                  label: "Tất cả tài nguyên" },
  { value: "estimates",         label: "Dự toán" },
  { value: "boq_items",         label: "BOQ" },
  { value: "suppliers",         label: "Nhà cung cấp" },
  { value: "rfq",               label: "RFQ" },
  { value: "change_orders",     label: "Change orders" },
  { value: "org_members",       label: "Thành viên" },
  { value: "invitations",       label: "Lời mời" },
  { value: "notification_preferences", label: "Tuỳ chọn thông báo" },
  { value: "handover_packages", label: "Gói bàn giao" },
  { value: "punchlist_lists",   label: "Punch list" },
  { value: "submittals",        label: "Submittals" },
  { value: "normalizer_rule",   label: "Luật chuẩn hoá" },
];

// Tone the action chips by intent — destructive / privileged actions
// (delete, role demotion) get a warmer color than routine approvals.
// Bulk imports + cron-driven events get a neutral slate — they're
// system-bearing but not "someone changed someone else's role" sensitive.
const ACTION_TONE: Record<string, string> = {
  "costpulse.estimate.approve":         "bg-emerald-100 text-emerald-800",
  "costpulse.boq.import":               "bg-slate-100 text-slate-700",
  "costpulse.suppliers.import":         "bg-slate-100 text-slate-700",
  "costpulse.rfq.slots_expired":        "bg-slate-100 text-slate-700",
  "pulse.change_order.approve":         "bg-emerald-100 text-emerald-800",
  "pulse.change_order.reject":          "bg-amber-100 text-amber-800",
  "org.member.role_change":             "bg-indigo-100 text-indigo-800",
  "org.member.remove":                  "bg-rose-100 text-rose-800",
  "org.invitation.create":              "bg-blue-100 text-blue-800",
  "org.invitation.revoke":              "bg-amber-100 text-amber-800",
  "org.invitation.accept":              "bg-emerald-100 text-emerald-800",
  "notifications.preference.update":    "bg-blue-100 text-blue-800",
  "handover.package.deliver":           "bg-purple-100 text-purple-800",
  "punchlist.list.sign_off":            "bg-emerald-100 text-emerald-800",
  "submittals.review.approve":          "bg-emerald-100 text-emerald-800",
  "submittals.review.approve_as_noted": "bg-emerald-100 text-emerald-800",
  "submittals.review.revise_resubmit":  "bg-amber-100 text-amber-800",
  "submittals.review.reject":           "bg-rose-100 text-rose-800",
  // Platform admin — indigo to flag "this affects multiple tenants"
  // visually distinct from the green/red of routine workflow events.
  "admin.normalizer_rule.create":       "bg-indigo-100 text-indigo-800",
  "admin.normalizer_rule.update":       "bg-indigo-100 text-indigo-800",
  "admin.normalizer_rule.delete":       "bg-rose-100 text-rose-800",
};

const PER_PAGE = 50;


function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("vi-VN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}


export default function AuditPage() {
  const [actionFilter, setActionFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [page, setPage] = useState(0);

  const filters = useMemo(
    () => ({
      action: actionFilter || undefined,
      resource_type: resourceFilter || undefined,
      limit: PER_PAGE,
      offset: page * PER_PAGE,
    }),
    [actionFilter, resourceFilter, page],
  );

  const { data, isLoading, isError, error } = useAuditEvents(filters);
  const events = data?.data ?? [];
  const total = data?.meta?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Nhật ký kiểm tra</h2>
        <p className="text-sm text-slate-600">
          Tất cả hành động nhạy cảm trong tổ chức — duyệt dự toán, change order,
          thay đổi vai trò thành viên, bàn giao gói. Append-only, không thể chỉnh sửa.
        </p>
      </div>

      {/* ---------------- Filters ---------------- */}
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center gap-2">
          <Filter size={14} className="text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-900">Bộ lọc</h3>
        </div>
        <div className="flex flex-wrap gap-3">
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Hành động
            </label>
            <select
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
                setPage(0);
              }}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
            >
              {ACTION_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Loại tài nguyên
            </label>
            <select
              value={resourceFilter}
              onChange={(e) => {
                setResourceFilter(e.target.value);
                setPage(0);
              }}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
            >
              {RESOURCE_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* ---------------- Events list ---------------- */}
      <section className="rounded-xl border border-slate-200 bg-white">
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-slate-500">Đang tải...</p>
        ) : isError ? (
          <div className="flex items-start gap-2 px-5 py-8 text-sm text-red-700">
            <ShieldAlert size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Không thể tải nhật ký</p>
              <p className="mt-0.5 text-xs">
                {(error as Error)?.message ?? "Bạn cần quyền admin để xem trang này."}
              </p>
            </div>
          </div>
        ) : events.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <FileText size={32} className="mx-auto mb-3 text-slate-400" />
            <p className="text-sm text-slate-500">
              Không có sự kiện nào khớp với bộ lọc.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {events.map((event) => (
              <AuditRow key={event.id} event={event} />
            ))}
          </ul>
        )}

        {/* Pagination */}
        {events.length > 0 && totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-xs">
            <span className="text-slate-500">
              {page * PER_PAGE + 1}–{page * PER_PAGE + events.length} / {total}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="rounded border border-slate-300 px-2.5 py-1 hover:bg-slate-50 disabled:opacity-40"
              >
                Trước
              </button>
              <span className="text-slate-600">
                Trang {page + 1} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="rounded border border-slate-300 px-2.5 py-1 hover:bg-slate-50 disabled:opacity-40"
              >
                Sau
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}


function AuditRow({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false);

  // Compact action label: drop the dotted module prefix when the i18n
  // map below has it; fall back to the raw string.
  const actionLabel =
    ACTION_FILTERS.find((f) => f.value === event.action)?.label ?? event.action;
  const tone = ACTION_TONE[event.action] ?? "bg-slate-100 text-slate-700";

  // Build a one-line "diff" string from before/after — so the row reads
  // at a glance without expanding.
  const diffSummary = summarizeDiff(event.before, event.after);

  return (
    <li className="px-5 py-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-3 text-left"
      >
        <span className="mt-1 shrink-0 text-slate-400">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}
            >
              {actionLabel}
            </span>
            {/* Cron-driven events have a null actor (e.g.
                `costpulse.rfq.slots_expired`). Render them as a
                visually distinct badge so admins skimming the log can
                tell "the system did this" from "Bob did this." Without
                it the row read as "blank user email" — looks like a
                bug, not a feature. */}
            {event.actor_email ? (
              <span className="text-xs text-slate-500">{event.actor_email}</span>
            ) : (
              <span className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-slate-700">
                system
              </span>
            )}
            {diffSummary && (
              <span className="text-xs text-slate-700">{diffSummary}</span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-slate-400">
            {formatTimestamp(event.created_at)}
            {event.ip && ` · ${event.ip}`}
            {event.resource_id && ` · ${event.resource_type}#${event.resource_id.slice(0, 8)}`}
          </p>
        </div>
      </button>

      {expanded && (
        <div className="mt-3 ml-7 grid gap-3 sm:grid-cols-2">
          <KvBlock title="Trước" data={event.before} />
          <KvBlock title="Sau" data={event.after} />
          {event.user_agent && (
            <p className="col-span-full text-[11px] text-slate-500">
              <span className="font-medium">User-Agent:</span>{" "}
              <span className="break-all">{event.user_agent}</span>
            </p>
          )}
        </div>
      )}
    </li>
  );
}


function KvBlock({
  title,
  data,
}: {
  title: string;
  data: Record<string, unknown>;
}) {
  const entries = Object.entries(data);
  return (
    <div className="rounded border border-slate-200 bg-slate-50/60 p-2 text-xs">
      <p className="mb-1 font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </p>
      {entries.length === 0 ? (
        <p className="text-slate-400">—</p>
      ) : (
        <dl className="space-y-0.5">
          {entries.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="text-slate-500">{k}:</dt>
              <dd className="font-mono text-slate-800">
                {typeof v === "object" ? JSON.stringify(v) : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}


function summarizeDiff(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): string | null {
  // Cheap one-liner for the row header. Walks the union of keys and
  // emits "k: from → to" pairs. Bounded at 2 keys so the row stays
  // single-line; expand for the full picture.
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const parts: string[] = [];
  for (const k of keys) {
    const b = before[k];
    const a = after[k];
    if (b === undefined && a !== undefined) {
      parts.push(`${k}: ∅ → ${String(a)}`);
    } else if (b !== undefined && a === undefined) {
      parts.push(`${k}: ${String(b)} → ∅`);
    } else if (b !== a) {
      parts.push(`${k}: ${String(b)} → ${String(a)}`);
    }
    if (parts.length >= 2) break;
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}
