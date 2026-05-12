"use client";

import Link from "next/link";
import { CheckCircle2, FileText, Users, XCircle } from "lucide-react";
import {
  ACCEPTANCE_LEVEL_LABEL,
  ACCEPTANCE_STATUS_LABEL,
} from "./types";
import type { AcceptanceStatus, RecordSummary } from "./types";

interface RecordCardProps {
  record: RecordSummary;
  href?: string;
}

const STATUS_STYLES: Record<AcceptanceStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  in_signoff: "bg-amber-100 text-amber-800",
  accepted: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-700",
  superseded: "bg-slate-200 text-slate-600",
};

const STATUS_ICON: Record<AcceptanceStatus, typeof FileText> = {
  draft: FileText,
  in_signoff: Users,
  accepted: CheckCircle2,
  rejected: XCircle,
  superseded: FileText,
};

export function RecordCard({ record, href }: RecordCardProps): JSX.Element {
  const Icon = STATUS_ICON[record.status];
  const signPct =
    record.signatories_total === 0
      ? 0
      : Math.round(
          (record.signatories_signed / record.signatories_total) * 100,
        );

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Icon className="mt-0.5 text-blue-600" size={20} />
          <div className="min-w-0">
            <p className="text-xs text-slate-500">{record.reference_no}</p>
            <h3 className="truncate font-semibold text-slate-900">
              {record.title}
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">
              {ACCEPTANCE_LEVEL_LABEL[record.acceptance_level]} ·{" "}
              {new Date(record.acceptance_date).toLocaleDateString("vi-VN")}
            </p>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[record.status]}`}
        >
          {ACCEPTANCE_STATUS_LABEL[record.status]}
        </span>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>Tiến độ ký</span>
          <span className="font-medium text-slate-900">
            {record.signatories_signed}/{record.signatories_total} ({signPct}%)
            {record.mandatory_pending > 0 && (
              <span className="ml-2 text-amber-700">
                · còn {record.mandatory_pending} bên bắt buộc
              </span>
            )}
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full transition-all ${
              record.status === "rejected" ? "bg-rose-500" : "bg-blue-500"
            }`}
            style={{ width: `${signPct}%` }}
          />
        </div>
      </div>
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- typedRoutes can't infer caller-supplied URL
  return href ? <Link href={href as any}>{body}</Link> : body;
}
