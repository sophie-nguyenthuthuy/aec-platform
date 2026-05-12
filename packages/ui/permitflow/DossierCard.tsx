"use client";

import Link from "next/link";
import { AlertTriangle, CalendarClock, FileCheck, Layers } from "lucide-react";
import {
  CLASSIFICATION_LABEL,
  DOSSIER_STATUS_LABEL,
  INVESTMENT_TYPE_LABEL,
  STAGE_CODE_LABEL,
  STAGE_STATUS_LABEL,
} from "./types";
import type { DossierStatus, DossierSummary } from "./types";

interface DossierCardProps {
  dossier: DossierSummary;
  href?: string;
}

const STATUS_STYLES: Record<DossierStatus, string> = {
  planning: "bg-slate-100 text-slate-700",
  in_progress: "bg-blue-100 text-blue-800",
  on_hold: "bg-amber-100 text-amber-800",
  completed: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-rose-100 text-rose-700",
};

export function DossierCard({ dossier, href }: DossierCardProps): JSX.Element {
  const donePct =
    dossier.stages_total === 0
      ? 0
      : Math.round((dossier.stages_approved / dossier.stages_total) * 100);

  const expiryDays = dossier.nearest_expiry
    ? daysUntil(dossier.nearest_expiry)
    : null;

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <FileCheck className="mt-0.5 text-blue-600" size={20} />
          <div>
            <h3 className="font-semibold text-slate-900">{dossier.name}</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              {CLASSIFICATION_LABEL[dossier.classification]} ·{" "}
              {INVESTMENT_TYPE_LABEL[dossier.investment_type]} · Tạo{" "}
              {new Date(dossier.created_at).toLocaleDateString("vi-VN")}
            </p>
          </div>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[dossier.status]}`}
        >
          {DOSSIER_STATUS_LABEL[dossier.status]}
        </span>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>Tiến độ giai đoạn</span>
          <span className="font-medium text-slate-900">
            {dossier.stages_approved}/{dossier.stages_total} ({donePct}%)
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full bg-blue-500 transition-all"
            style={{ width: `${donePct}%` }}
          />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs">
        <Stat
          icon={Layers}
          label="Giai đoạn kế tiếp"
          value={
            dossier.next_stage_code
              ? STAGE_CODE_LABEL[dossier.next_stage_code]
              : "—"
          }
          sub={
            dossier.next_stage_status
              ? STAGE_STATUS_LABEL[dossier.next_stage_status]
              : undefined
          }
        />
        {dossier.nearest_expiry && (
          <Stat
            icon={expiryDays !== null && expiryDays <= 30 ? AlertTriangle : CalendarClock}
            label="Hết hiệu lực sớm nhất"
            value={new Date(dossier.nearest_expiry).toLocaleDateString("vi-VN")}
            sub={expiryDays !== null ? `còn ${expiryDays} ngày` : undefined}
            tone={
              expiryDays !== null && expiryDays <= 7
                ? "red"
                : expiryDays !== null && expiryDays <= 30
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
  icon: typeof Layers;
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
