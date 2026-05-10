"use client";

/**
 * Project-scoped audit feed (cycle S3) — `/projects/[id]/audit`.
 *
 * Same row shape as `/settings/audit` but scoped to one project.
 * The backend JOINs across the five project-scoped resource
 * tables (change_orders, punch_lists, handover_packages,
 * submittals, rfqs) so this page renders only events that touched
 * THIS project.
 *
 * Why a dedicated page rather than a `?project_id=X` filter on
 * /settings/audit:
 *   * Project admins typically navigate to a project's URL first,
 *     then drill into "what happened to it." A standalone page
 *     under /projects/[id]/audit matches that mental model.
 *   * The org-wide audit page lists events across every project +
 *     org-level events (member changes, webhook rotations).
 *     Project-scoped is a STRICT subset; surfacing it as a sibling
 *     route avoids "where do I go for project audit?" confusion.
 *
 * Filters: action / actor_kind / since_days. resource_type is
 * implicitly limited to the five project-scoped types by the
 * backend JOIN.
 */

import Link from "next/link";
import { use, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Filter,
  ShieldAlert,
} from "lucide-react";

import { type AuditEvent, useProjectAuditEvents } from "@/hooks/audit";
import { auditResourceHref } from "@/lib/audit-resource-routes";


// Subset of `services/audit.AuditAction` whose `resource_type` is
// project-scoped — these are the only actions that show up on this
// page. Others (org.invitation.create, webhooks.subscription.rotate_secret,
// etc) are filtered out by the backend's JOIN scope.
const PROJECT_ACTION_FILTERS: Array<{ value: string; label: string }> = [
  { value: "", label: "Tất cả hành động" },
  { value: "pulse.change_order.approve", label: "Duyệt change order" },
  { value: "pulse.change_order.reject", label: "Từ chối change order" },
  { value: "punchlist.list.sign_off", label: "Ký nghiệm thu punch list" },
  { value: "submittals.review.approve", label: "Duyệt submittal" },
  { value: "submittals.review.approve_as_noted", label: "Duyệt có ghi chú" },
  { value: "submittals.review.revise_resubmit", label: "Yêu cầu nộp lại" },
  { value: "submittals.review.reject", label: "Từ chối submittal" },
  { value: "handover.package.deliver", label: "Bàn giao gói" },
  { value: "costpulse.rfq.slots_expired", label: "RFQ hết hạn (tự động)" },
];

const TIME_WINDOWS: Array<{ value: number | null; label: string }> = [
  { value: 1, label: "24h" },
  { value: 7, label: "7d" },
  { value: 30, label: "30d" },
  { value: null, label: "Tất cả" },
];

const ACTOR_KINDS: Array<{
  value: "user" | "api_key" | "system" | "";
  label: string;
}> = [
  { value: "", label: "Mọi loại actor" },
  { value: "user", label: "Người dùng" },
  { value: "api_key", label: "API key" },
  { value: "system", label: "Hệ thống (cron)" },
];

const PER_PAGE = 50;


export default function ProjectAuditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  // Next.js 15 — params is async; `use(...)` unwraps in client components.
  const { id: projectId } = use(params);

  const [actionFilter, setActionFilter] = useState("");
  const [actorKind, setActorKind] = useState<"" | "user" | "api_key" | "system">("");
  const [sinceDays, setSinceDays] = useState<number | null>(30);
  const [page, setPage] = useState(0);

  const filters = useMemo(
    () => ({
      action: actionFilter || undefined,
      actor_kind: actorKind || undefined,
      since_days: sinceDays ?? undefined,
      limit: PER_PAGE,
      offset: page * PER_PAGE,
    }),
    [actionFilter, actorKind, sinceDays, page],
  );

  const { data, isLoading, isError, error } = useProjectAuditEvents(
    projectId,
    filters,
  );
  const events: AuditEvent[] = data?.data ?? [];
  const total = data?.meta?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <div className="space-y-6">
      <Link
        href={`/projects/${projectId}`}
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
      >
        <ChevronLeft size={14} />
        Quay lại dự án
      </Link>

      <div>
        <h2 className="text-2xl font-bold text-slate-900">Nhật ký dự án</h2>
        <p className="text-sm text-slate-600">
          Tất cả hành động nhạy cảm liên quan đến dự án này — change order,
          submittal review, punch list sign-off, RFQ, handover. Append-only,
          không thể chỉnh sửa. Dành cho admin dự án và compliance review.
        </p>
      </div>

      {/* ---------- Filters ---------- */}
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex items-center gap-2">
          <Filter size={14} className="text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-900">Bộ lọc</h3>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Cửa sổ
          </span>
          {TIME_WINDOWS.map((w) => (
            <button
              key={w.label}
              type="button"
              onClick={() => {
                setSinceDays(w.value);
                setPage(0);
              }}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                sinceDays === w.value
                  ? "bg-indigo-600 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {w.label}
            </button>
          ))}
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
              {PROJECT_ACTION_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Actor
            </label>
            <select
              value={actorKind}
              onChange={(e) => {
                setActorKind(e.target.value as typeof actorKind);
                setPage(0);
              }}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
            >
              {ACTOR_KINDS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* ---------- Events list ---------- */}
      <section className="rounded-xl border border-slate-200 bg-white">
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-slate-500">Đang tải...</p>
        ) : isError ? (
          <ErrorBanner error={error as Error | null} />
        ) : events.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <AlertTriangle size={28} className="mx-auto mb-3 text-slate-400" />
            <p className="text-sm text-slate-500">
              Không có sự kiện nào khớp với bộ lọc trong cửa sổ này.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {events.map((e) => (
              <ProjectAuditRow key={e.id} event={e} />
            ))}
          </ul>
        )}

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
                onClick={() =>
                  setPage((p) => Math.min(totalPages - 1, p + 1))
                }
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


function ProjectAuditRow({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false);
  const actionLabel =
    PROJECT_ACTION_FILTERS.find((f) => f.value === event.action)?.label ??
    event.action;
  const href = auditResourceHref(event.resource_type, event.resource_id);

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
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              {actionLabel}
            </span>
            {event.actor_email ? (
              <span className="text-xs text-slate-500">{event.actor_email}</span>
            ) : event.actor_api_key_name ? (
              <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-1.5 py-0.5 text-[11px] text-blue-800">
                <span className="font-mono text-[9px] uppercase tracking-wide">
                  key
                </span>
                <span className="font-medium">{event.actor_api_key_name}</span>
              </span>
            ) : (
              <span className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-slate-700">
                system
              </span>
            )}
          </div>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[11px] text-slate-400">
            <span>
              {new Date(event.created_at).toLocaleString("vi-VN", {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
            {event.resource_id && (
              <>
                <span>·</span>
                {href ? (
                  <Link
                    href={href}
                    onClick={(ev) => ev.stopPropagation()}
                    className="text-blue-600 hover:underline"
                  >
                    {event.resource_type}#{event.resource_id.slice(0, 8)}
                  </Link>
                ) : (
                  <span>
                    {event.resource_type}#{event.resource_id.slice(0, 8)}
                  </span>
                )}
              </>
            )}
          </p>
        </div>
      </button>

      {expanded && (
        <div className="mt-3 ml-7 grid gap-3 sm:grid-cols-2">
          <KvBlock title="Trước" data={event.before} />
          <KvBlock title="Sau" data={event.after} />
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


function ErrorBanner({ error }: { error: Error | null }) {
  const msg = error?.message ?? "";
  const isForbidden = msg.includes("403") || /forbidden/i.test(msg);
  return (
    <div className="flex items-start gap-2 px-5 py-8 text-sm text-red-700">
      {isForbidden ? (
        <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      ) : (
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      )}
      <p>
        {isForbidden
          ? "Bạn cần quyền admin để xem nhật ký dự án."
          : msg || "Không thể tải nhật ký."}
      </p>
    </div>
  );
}
