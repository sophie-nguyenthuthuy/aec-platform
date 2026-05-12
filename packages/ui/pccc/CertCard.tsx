"use client";

import Link from "next/link";
import { AlertTriangle, CalendarClock, Flame, ListChecks } from "lucide-react";
import {
  BUILDING_CLASS_LABEL,
  CERT_STATUS_LABEL,
  CERT_TYPE_LABEL,
} from "./types";
import type { CertStatus, CertSummary } from "./types";

interface CertCardProps {
  cert: CertSummary;
  href?: string;
}

const STATUS_STYLES: Record<CertStatus, string> = {
  planning: "bg-slate-100 text-slate-700",
  submitted: "bg-blue-100 text-blue-800",
  inspection_scheduled: "bg-indigo-100 text-indigo-800",
  rfi: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  conditional: "bg-yellow-100 text-yellow-800",
  rejected: "bg-rose-100 text-rose-700",
  expired: "bg-slate-300 text-slate-700",
};

export function CertCard({ cert, href }: CertCardProps): JSX.Element {
  const expiryDays = cert.expiry_date ? daysUntil(cert.expiry_date) : null;
  const checklistPct =
    cert.checklist_total === 0
      ? 0
      : Math.round((cert.checklist_compliant / cert.checklist_total) * 100);

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-red-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Flame className="mt-0.5 text-red-600" size={20} />
          <div className="min-w-0">
            <p className="text-xs text-slate-500">{cert.reference_no}</p>
            <h3 className="font-semibold text-slate-900">
              {CERT_TYPE_LABEL[cert.cert_type]}
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Hazard {cert.hazard_category} · {BUILDING_CLASS_LABEL[cert.building_class]} ·{" "}
              {cert.pc07_unit}
            </p>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[cert.status]}`}
        >
          {CERT_STATUS_LABEL[cert.status]}
        </span>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>Checklist QCVN 06:2022</span>
          <span className="font-medium text-slate-900">
            {cert.checklist_compliant}/{cert.checklist_total} ({checklistPct}%)
            {cert.checklist_non_compliant > 0 && (
              <span className="ml-2 text-rose-700">
                · {cert.checklist_non_compliant} không đạt
              </span>
            )}
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${checklistPct}%` }}
          />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs">
        <Stat
          icon={ListChecks}
          label="Số lượt kiểm tra"
          value={String(cert.inspection_count)}
        />
        {cert.expiry_date && (
          <Stat
            icon={
              expiryDays !== null && expiryDays <= 30
                ? AlertTriangle
                : CalendarClock
            }
            label="Hết hiệu lực"
            value={new Date(cert.expiry_date).toLocaleDateString("vi-VN")}
            sub={expiryDays !== null ? `còn ${expiryDays} ngày` : undefined}
            tone={
              expiryDays !== null && expiryDays <= 30
                ? "red"
                : expiryDays !== null && expiryDays <= 90
                  ? "amber"
                  : "slate"
            }
          />
        )}
      </div>
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- typedRoutes can't infer caller-supplied URL
  return href ? <Link href={href as any}>{body}</Link> : body;
}

function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(iso);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

type StatTone = "slate" | "amber" | "red";
const TONE_STYLES: Record<StatTone, string> = {
  slate: "text-slate-500",
  amber: "text-amber-600",
  red: "text-red-600",
};

function Stat({
  icon: Icon,
  label,
  value,
  sub,
  tone = "slate",
}: {
  icon: typeof ListChecks;
  label: string;
  value: string;
  sub?: string;
  tone?: StatTone;
}): JSX.Element {
  return (
    <div className="flex items-center gap-1.5">
      <Icon size={14} className={TONE_STYLES[tone]} />
      <div className="leading-tight">
        <div className="text-slate-600">{label}</div>
        <div className={`font-medium ${TONE_STYLES[tone]}`}>
          {value}
          {sub && (
            <span className="ml-1 font-normal text-slate-500">({sub})</span>
          )}
        </div>
      </div>
    </div>
  );
}
