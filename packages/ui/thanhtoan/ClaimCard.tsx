"use client";

import Link from "next/link";
import { Banknote, CalendarClock, ListChecks } from "lucide-react";
import { CLAIM_STATUS_LABEL, formatVnd } from "./types";
import type { ClaimStatus, ClaimSummary } from "./types";

interface ClaimCardProps {
  claim: ClaimSummary;
  href?: string;
}

const STATUS_STYLES: Record<ClaimStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  submitted: "bg-blue-100 text-blue-800",
  in_review: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-700",
  paid: "bg-emerald-200 text-emerald-900",
  cancelled: "bg-slate-200 text-slate-600",
};

export function ClaimCard({ claim, href }: ClaimCardProps): JSX.Element {
  const overdue =
    claim.due_at &&
    !claim.paid_at &&
    new Date(claim.due_at) < new Date(new Date().toDateString());

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Banknote className="mt-0.5 text-blue-600" size={20} />
          <div className="min-w-0">
            <p className="text-xs text-slate-500">
              #{claim.sequence} · {claim.claim_no}
            </p>
            <h3 className="font-semibold text-slate-900">
              {formatVnd(claim.net_payable_vnd)}
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">
              {new Date(claim.period_start).toLocaleDateString("vi-VN")} —{" "}
              {new Date(claim.period_end).toLocaleDateString("vi-VN")}
            </p>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[claim.status]}`}
        >
          {CLAIM_STATUS_LABEL[claim.status]}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-slate-600">
        <div className="flex items-center gap-1.5">
          <ListChecks size={14} className="text-slate-500" />
          <span className="font-medium text-slate-900">{claim.line_count}</span>
          <span>hạng mục</span>
        </div>
        {claim.due_at && (
          <div
            className={`flex items-center gap-1.5 ${overdue ? "text-rose-600" : "text-slate-500"}`}
          >
            <CalendarClock size={14} />
            <span>
              {overdue ? "Quá hạn" : "Hạn"}:{" "}
              {new Date(claim.due_at).toLocaleDateString("vi-VN")}
            </span>
          </div>
        )}
        {claim.paid_at && (
          <div className="flex items-center gap-1.5 text-emerald-700">
            <CalendarClock size={14} />
            <span>
              Đã trả: {new Date(claim.paid_at).toLocaleDateString("vi-VN")}
            </span>
          </div>
        )}
      </div>
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- typedRoutes can't infer caller-supplied URL
  return href ? <Link href={href as any}>{body}</Link> : body;
}
