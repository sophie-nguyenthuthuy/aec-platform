"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, History } from "lucide-react";

import { useAuditEvents, type AuditEvent } from "@/hooks/audit";


// Same Vietnamese labels as the /settings/audit page — duplicated here
// rather than imported because that page is full-route-scoped to admin
// and we don't want this small panel to depend on its module.
const ACTION_LABEL: Record<string, string> = {
  "costpulse.estimate.approve": "Duyệt dự toán",
  "pulse.change_order.approve": "Duyệt change order",
  "pulse.change_order.reject":  "Từ chối change order",
  "org.member.role_change":     "Đổi vai trò thành viên",
  "org.member.remove":          "Xóa thành viên",
  "org.invitation.create":      "Tạo lời mời",
  "org.invitation.revoke":      "Thu hồi lời mời",
  "org.invitation.accept":      "Chấp nhận lời mời",
  "handover.package.deliver":   "Bàn giao gói",
};


/**
 * Compact "who-did-what" panel pinned to one resource.
 *
 * Drop on a project detail page, change-order detail, etc. — the same
 * `/api/v1/audit/events` endpoint that powers the org-wide audit
 * page, just with `resource_type` + `resource_id` narrowed.
 *
 * Admin-only: the audit endpoint enforces `require_min_role(Role.ADMIN)`,
 * so a viewer / member sees a 403 from the hook and we render a
 * "no access" hint instead of leaking error UI. The panel intentionally
 * fails *quietly* — it's a sidebar enhancement, not the primary UX.
 */
export function ResourceAuditPanel({
  resourceType,
  resourceId,
  limit = 10,
}: {
  resourceType: string;
  resourceId: string;
  limit?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading, isError, error } = useAuditEvents({
    resource_type: resourceType,
    resource_id: resourceId,
    limit,
  });

  // 403 = caller isn't admin/owner. Don't render the panel at all in
  // that case — viewers shouldn't see "you can't see this" framing for
  // a feature that isn't theirs to begin with.
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status: number }).status
      : null;
  if (isError && status === 403) return null;

  const events = data?.data ?? [];
  if (!isLoading && events.length === 0) return null;  // nothing to show

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <header className="flex items-center justify-between px-4 py-2.5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 text-sm font-medium text-slate-700"
          aria-expanded={expanded}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <History size={14} className="text-slate-400" />
          Lịch sử kiểm tra
          {events.length > 0 && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-normal text-slate-600">
              {events.length}
            </span>
          )}
        </button>
      </header>

      {expanded && (
        <div className="border-t border-slate-100">
          {isLoading ? (
            <p className="px-4 py-3 text-xs text-slate-500">Đang tải...</p>
          ) : isError ? (
            <p className="px-4 py-3 text-xs text-slate-500">
              Không thể tải lịch sử.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {events.map((e) => (
                <AuditRow key={e.id} event={e} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}


function AuditRow({ event }: { event: AuditEvent }) {
  const label = ACTION_LABEL[event.action] ?? event.action;
  const diff = summarizeDiff(event.before, event.after);
  const ts = new Date(event.created_at).toLocaleString("vi-VN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <li className="px-4 py-2 text-xs">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-slate-800">{label}</span>
        <span className="shrink-0 text-slate-400">{ts}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-2 text-slate-500">
        <span>{event.actor_email ?? "system"}</span>
        {diff && <span className="text-slate-700">{diff}</span>}
      </div>
    </li>
  );
}


/** One-line diff summary identical to the org-wide audit page's logic. */
function summarizeDiff(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): string | null {
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
