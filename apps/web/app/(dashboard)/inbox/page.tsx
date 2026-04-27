"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  Clipboard,
  ClipboardCheck,
  FileSignature,
  FileText,
  HelpCircle,
  Inbox as InboxIcon,
  Replace,
  Sparkles,
} from "lucide-react";
import type { ReactNode } from "react";

import { useInbox } from "@/hooks/inbox";
import type { InboxBucket, InboxItem, InboxItemKind } from "@aec/types/inbox";

const KIND_META: Record<
  InboxItemKind,
  { label: string; icon: ReactNode; tone: string }
> = {
  rfi: {
    label: "RFI",
    icon: <HelpCircle size={14} />,
    tone: "bg-indigo-50 text-indigo-700",
  },
  punch_item: {
    label: "Punch",
    icon: <FileSignature size={14} />,
    tone: "bg-rose-50 text-rose-700",
  },
  defect: {
    label: "Defect",
    icon: <ClipboardCheck size={14} />,
    tone: "bg-purple-50 text-purple-700",
  },
  submittal: {
    label: "Submittal",
    icon: <Clipboard size={14} />,
    tone: "bg-blue-50 text-blue-700",
  },
  change_order: {
    label: "CO",
    icon: <Replace size={14} />,
    tone: "bg-amber-50 text-amber-800",
  },
  co_candidate: {
    label: "CO (AI)",
    icon: <Sparkles size={14} />,
    tone: "bg-emerald-50 text-emerald-700",
  },
};

const BUCKET_LABEL: Record<InboxBucket, string> = {
  assigned_to_me: "Việc giao cho tôi",
  awaiting_review: "Chờ review / duyệt",
};

const SEVERITY_TONE: Record<string, string> = {
  high: "text-red-700",
  critical: "text-red-700 font-semibold",
  medium: "text-amber-700",
  low: "text-slate-500",
  // CO uses normal/high/urgent for priority — fall through.
};

function _isOverdue(due: string | null | undefined): boolean {
  if (!due) return false;
  return new Date(due).getTime() < Date.now();
}

function _formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function InboxPage() {
  const { data, isLoading, isError } = useInbox();
  const [filterKind, setFilterKind] = useState<InboxItemKind | "all">("all");

  const items = data?.items ?? [];
  const filtered =
    filterKind === "all" ? items : items.filter((i) => i.kind === filterKind);

  const buckets: InboxBucket[] = ["assigned_to_me", "awaiting_review"];
  const itemsByBucket: Record<InboxBucket, InboxItem[]> = {
    assigned_to_me: filtered.filter((i) => i.bucket === "assigned_to_me"),
    awaiting_review: filtered.filter((i) => i.bucket === "awaiting_review"),
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Hôm nay</h2>
        <p className="text-sm text-slate-600">
          Tổng hợp việc đang chờ trên 14 module — RFI giao cho bạn, punch
          item, defect, submittal chờ review, change order chờ duyệt, và đề
          xuất CO từ AI.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(["all", ...Object.keys(KIND_META)] as Array<InboxItemKind | "all">).map((k) => {
          const meta = k === "all" ? null : KIND_META[k as InboxItemKind];
          const count =
            k === "all"
              ? items.length
              : items.filter((i) => i.kind === k).length;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setFilterKind(k)}
              className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${
                filterKind === k
                  ? "bg-blue-600 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {meta?.icon}
              {k === "all" ? "Tất cả" : meta?.label}
              <span className="ml-1 rounded-full bg-slate-100 px-1.5 text-[10px] text-slate-700">
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <p className="text-sm text-red-600">
          Không thể tải inbox. Vui lòng thử lại.
        </p>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <InboxIcon size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
          <p className="text-sm text-slate-500">Trống — không có gì chờ.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {buckets.map((bucket) => {
            const list = itemsByBucket[bucket];
            if (list.length === 0) return null;
            return (
              <section key={bucket}>
                <h3 className="mb-2 text-sm font-semibold text-slate-900">
                  {BUCKET_LABEL[bucket]}{" "}
                  <span className="ml-1 text-xs font-normal text-slate-500">
                    ({list.length})
                  </span>
                </h3>
                <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
                  {list.map((it) => (
                    <Row key={`${it.kind}:${it.id}`} item={it} />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Row({ item }: { item: InboxItem }) {
  const meta = KIND_META[item.kind as InboxItemKind];
  const overdue = _isOverdue(item.due_date);
  return (
    <li>
      <Link
        href={item.deep_link}
        className="flex items-baseline gap-3 px-4 py-3 transition hover:bg-slate-50"
      >
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${meta.tone}`}
        >
          {meta.icon}
          {meta.label}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900">
            {item.title}
          </p>
          <p className="text-xs text-slate-500">
            {item.subtitle ? <span className="font-mono">{item.subtitle}</span> : null}
            {item.subtitle && item.project_name ? " · " : null}
            {item.project_name ?? "—"}
            {item.status ? ` · ${item.status}` : ""}
            {item.severity ? (
              <span className={`ml-1 ${SEVERITY_TONE[item.severity] ?? ""}`}>
                · {item.severity}
              </span>
            ) : null}
          </p>
        </div>
        <div className="shrink-0 text-right text-[11px]">
          {item.due_date ? (
            <p
              className={`flex items-center justify-end gap-1 ${
                overdue ? "font-medium text-red-700" : "text-slate-600"
              }`}
            >
              {overdue && <AlertTriangle size={11} />}
              Hạn {_formatDate(item.due_date)}
            </p>
          ) : item.created_at ? (
            <p className="text-slate-400">{_formatDate(item.created_at)}</p>
          ) : null}
        </div>
      </Link>
    </li>
  );
}

const _STATIC_INFO = {
  // FileText is imported but only referenced via KIND_META; silence
  // unused-import warnings if KIND_META ever loses an icon.
  _: <FileText size={1} />,
};
void _STATIC_INFO;
