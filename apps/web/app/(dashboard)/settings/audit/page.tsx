"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Filter, ShieldAlert } from "lucide-react";

import { type AuditEvent, useAuditEvents } from "@/hooks/audit";


// Closed set — mirrors `services/audit.AuditAction` literal on the API.
// Keeping it client-side as a list lets us label-i18n + render a clean
// dropdown without an extra round-trip.
const ACTION_FILTERS: Array<{ value: string; label: string }> = [
  { value: "",                           label: "Tất cả hành động" },
  { value: "costpulse.estimate.approve", label: "Duyệt dự toán" },
  { value: "pulse.change_order.approve", label: "Duyệt change order" },
  { value: "pulse.change_order.reject",  label: "Từ chối change order" },
  { value: "org.member.role_change",     label: "Đổi vai trò thành viên" },
  { value: "org.member.remove",          label: "Xóa thành viên" },
  { value: "org.invitation.create",      label: "Tạo lời mời" },
  { value: "org.invitation.revoke",      label: "Thu hồi lời mời" },
  { value: "org.invitation.accept",      label: "Chấp nhận lời mời" },
  { value: "handover.package.deliver",   label: "Bàn giao gói" },
];

const RESOURCE_FILTERS: Array<{ value: string; label: string }> = [
  { value: "",              label: "Tất cả tài nguyên" },
  { value: "estimates",     label: "Dự toán" },
  { value: "change_orders", label: "Change orders" },
  { value: "org_members",   label: "Thành viên" },
  { value: "invitations",   label: "Lời mời" },
  { value: "handover_packages", label: "Gói bàn giao" },
];

// Tone the action chips by intent — destructive / privileged actions
// (delete, role demotion) get a warmer color than routine approvals.
const ACTION_TONE: Record<string, string> = {
  "costpulse.estimate.approve": "bg-emerald-100 text-emerald-800",
  "pulse.change_order.approve": "bg-emerald-100 text-emerald-800",
  "pulse.change_order.reject":  "bg-amber-100 text-amber-800",
  "org.member.role_change":     "bg-indigo-100 text-indigo-800",
  "org.member.remove":          "bg-rose-100 text-rose-800",
  "org.invitation.create":      "bg-blue-100 text-blue-800",
  "org.invitation.revoke":      "bg-amber-100 text-amber-800",
  "org.invitation.accept":      "bg-emerald-100 text-emerald-800",
  "handover.package.deliver":   "bg-purple-100 text-purple-800",
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
            <span className="text-xs text-slate-500">
              {event.actor_email ?? "system"}
            </span>
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
